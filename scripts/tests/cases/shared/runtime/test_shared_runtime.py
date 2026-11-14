"""Shared runtime contracts without launching processes or loading model libraries."""

import contextlib
import ctypes
import io
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.benchmarks.shared.resident_http import ResidentHttp
from scripts.config import models as model_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.launchers.asr.shared.resident_profiles import build_server_command, profiles
from scripts.launchers.shared.native_abi.cabi import structures
from scripts.launchers.shared.native_abi.native_library import NativeLibrary
from scripts.launchers.shared.services import native, process
from scripts.launchers.shared.transport.multipart import audio_upload
from scripts.shared import wait
from scripts.tests.shared import process_fixtures
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.process_fixtures import exited_process, inspected_process, running_process


class SweepMessageTests(unittest.TestCase):
    def _sweep(self, known):
        from unittest.mock import patch

        from scripts.launchers import launch_util

        with (
            patch.object(launch_util, "listening_process_ids", return_value=[77]),
            patch.object(launch_util, "process_start_time", return_value=100.0),
            patch.object(launch_util, "kill_process_tree"),
            patch("builtins.print") as printed,
            patch.object(launch_util.sys, "platform", "win32"),
        ):
            launch_util.sweep_escaped_children(5002, 99.0, known)
        return printed.call_args.args[0]

    def test_a_known_descendant_is_reported_as_stopped_not_escaped(self):
        self.assertIn("stopped remaining child", self._sweep({77}))

    def test_a_pid_outside_the_sampled_tree_is_still_reported_as_escaped(self):
        self.assertIn("swept escaped child", self._sweep({88}))

    def test_the_descendant_set_is_sampled_before_the_kill_severs_the_tree(self):
        from unittest.mock import patch

        from scripts.launchers import launch_util

        with (
            patch.object(launch_util, "process_start_time", return_value=100.0),
            patch.object(launch_util, "descendant_pids", return_value={5}) as sampled,
            patch.object(launch_util, "subprocess") as run,
            patch.object(launch_util, "sweep_escaped_children") as sweep,
            patch.object(launch_util, "_pid_alive", return_value=False),
        ):
            run.run.return_value = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            launch_util.kill_process_tree(4242, ports=5002)
        sampled.assert_called_once_with(4242)
        self.assertEqual(sweep.call_args.args[2], {5})


class OwnedLaunchTests(unittest.TestCase):
    def _launch(self, bind_job):
        from unittest.mock import patch

        from scripts.launchers import launch_util

        process = process_fixtures.fake_process(pid=4242)
        with (
            patch.object(launch_util.subprocess, "Popen", return_value=process),
            patch.object(launch_util, "_clear_requested_ports"),
            patch.object(launch_util, "get_gpu_memory_snapshot"),
            patch.object(launch_util, "_child_environment", return_value={}),
            patch.object(launch_util, "assign_process_to_job") as assign,
            patch.object(launch_util, "prune_stale_temp"),
        ):
            launch_util.launch_process(["exe"], "title", bind_job=bind_job)
        return assign

    def test_an_owned_launch_joins_the_kill_on_close_job(self):
        self.assertEqual(self._launch(True).call_args.args, (4242,))

    def test_a_user_launched_service_is_left_out_of_the_job(self):
        self.assertFalse(self._launch(False).called)


class ReadinessRouteTests(unittest.TestCase):
    def test_kobold_ports_are_probed_on_a_route_kobold_serves(self):
        from scripts.launchers import launch_util
        from scripts.launchers import launcher_config as cfg

        self.assertEqual(launch_util.backend_for_port(cfg.KOBOLDCPP_PORT), "koboldcpp")
        self.assertEqual(launch_util.backend_for_port(cfg.KOBOLDCPP_SERVICE.streaming_ui_port), "koboldcpp")
        self.assertEqual(launch_util.ready_url("koboldcpp", 5002), "http://127.0.0.1:5002/api/v1/model")

    def test_other_ports_keep_the_llama_cpp_and_sd_cpp_routes(self):
        from scripts.launchers import launch_util
        from scripts.launchers import launcher_config as cfg

        self.assertEqual(launch_util.backend_for_port(cfg.SDCPP_SERVICE.port), "sdcpp")
        self.assertEqual(launch_util.backend_for_port(cfg.LLAMACPP_SERVICE.port), "llamacpp")


class SharedRuntimeTests(unittest.TestCase):
    def test_python_redirector_resolves_only_its_owned_module_worker(self):
        child = inspected_process(pid=11, parent=10, command=["python", "-m", "owned.module"])
        root = inspected_process(pid=10, parent=1, command=["python", "-m", "owned.module"], children=[child])
        parent = running_process(pid=10)
        with patch("psutil.Process", return_value=root):
            worker = process.owned_module_worker(parent, "owned.module")
            self.assertEqual(worker.pid, 11)
            self.assertIsNone(worker.poll())
            with self.assertRaisesRegex(RuntimeError, "Cannot identify"):
                process.owned_module_worker(parent, "unrelated.module")

    def test_readiness_rejects_dead_process_even_if_probe_is_stale(self):
        worker = exited_process(exit_code=4)
        probe = Mock(return_value=True)
        with self.assertRaisesRegex(RuntimeError, "exited"):
            wait.wait_ready(probe, 1, label="fixture", process=worker)
        probe.assert_not_called()

    def test_readiness_deadline_is_bounded_without_real_sleep(self):
        worker = running_process()
        with (
            patch.object(wait.time, "monotonic", side_effect=[0, 0, 2]),
            patch.object(wait.time, "sleep") as sleep,
            self.assertRaises(TimeoutError),
        ):
            wait.wait_ready(lambda: False, 1, label="fixture", process=worker)
        sleep.assert_called_once_with(0.2)

    def test_readiness_heartbeat_reports_elapsed_against_the_budget(self):
        with (
            patch.object(wait.time, "monotonic", side_effect=[0, 0, 11, 25]),
            patch.object(wait.time, "sleep"),
            contextlib.redirect_stdout(stream := io.StringIO()),
            self.assertRaises(TimeoutError),
        ):
            wait.wait_ready(lambda: False, 20, label="Strata", interval=1, heartbeat_seconds=10)
        self.assertIn("[WAIT] Strata still starting: 11 s of 20 s", stream.getvalue())

    def test_readiness_aborts_with_the_callers_reason(self):
        with self.assertRaisesRegex(RuntimeError, "guard tripped"):
            wait.wait_ready(lambda: False, 5, label="fixture", fail=lambda: "guard tripped")

    def test_owned_graceful_cleanup_escalates_only_after_timeout(self):
        worker = running_process(pid=12345, wait_timeouts=1)
        with patch.object(process.launch_util, "kill_process_tree") as kill:
            process.stop_owned(worker, timeout=1, graceful=True)
        worker.terminate.assert_called_once()
        kill.assert_called_once_with(12345)

    def test_healthy_mismatched_service_is_never_stopped_or_replaced(self):
        with (
            patch.object(native.launch_util, "launch_process") as start,
            patch.object(native, "stop_owned") as stop,
            self.assertRaisesRegex(RuntimeError, "does not match"),
        ):
            native.start_server([], [], 12345, "fixture", lambda: True, lambda: False)
        start.assert_not_called()
        stop.assert_not_called()

    def test_resident_startup_failure_cleans_owned_process_and_log(self):
        worker = running_process(pid=12345)
        with CasePaths(__file__).temporary_directory() as folder:
            server = ResidentHttp(["fixture.exe"], 12345, Path(folder) / "server.log", model_identity="fixture")
            with (
                patch("scripts.benchmarks.shared.resident_http.launch_util.port_listening", return_value=False),
                patch("scripts.benchmarks.shared.resident_http.launch_util.assign_process_to_job"),
                patch("scripts.benchmarks.shared.resident_http.subprocess.Popen", return_value=worker),
                patch("scripts.benchmarks.shared.resident_http.wait_ready", side_effect=TimeoutError("fixture")),
                patch("scripts.benchmarks.shared.resident_http.stop_owned") as stop,
                self.assertRaises(TimeoutError),
                server.lifecycle as timer,
            ):
                timer.prepare(server.start, combined=True)
            stop.assert_called_once_with(worker, timeout=10)
            self.assertTrue(server.stream is not None and server.stream.closed)

    def test_server_commands_use_catalog_model_and_requested_port(self):
        for name, profile in ASR_FILE_PROFILES.items():
            if profile.server_arguments is None:
                continue
            command = build_server_command(name, 19123)
            self.assertEqual(command[0], str(profile.server_executable or profile.executable))
            if profile.audio_family:
                from scripts.launchers.asr.shared.resident_profiles import audio_config

                self.assertEqual(audio_config(name)["models"][0]["path"], str(model_cfg.path(profile.models[0])))
                self.assertIn("{config}", command)
            else:
                self.assertIn(str(model_cfg.path(profile.models[0])), command)
            self.assertEqual(command[command.index("--port") + 1], "19123")
        for name, (command, _) in profiles(19123).items():
            self.assertEqual(command[command.index("--port") + 1], "19123")

    def test_multipart_binary_roundtrip_uses_independent_mime_parser(self):
        audio = b"\x00\xff\r\nRIFF\x80"
        body, kind = audio_upload(audio, {"language": "fr", "model": "fixture"})
        message = BytesParser(policy=policy.default).parsebytes(f"Content-Type: {kind}\r\n\r\n".encode() + body)
        fields = {
            part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.iter_parts()
        }
        self.assertEqual(fields, {"file": audio, "language": b"fr", "model": b"fixture"})
        with self.assertRaises(ValueError):
            audio_upload(audio, {}, filename='bad"name.wav')

    def test_library_load_failure_closes_dll_search_paths(self):
        directory = Mock()
        directory.__enter__ = Mock(return_value=directory)
        directory.__exit__ = Mock()
        with (
            patch("scripts.launchers.shared.native_abi.native_library.os.add_dll_directory", return_value=directory),
            patch("scripts.launchers.shared.native_abi.native_library.ctypes.CDLL", side_effect=OSError("fixture")),
            self.assertRaises(OSError),
        ):
            NativeLibrary(Path("fixture.dll"), search_dirs=(Path("fixture"),))
        directory.__exit__.assert_called_once()

    def test_abi_reader_rejects_unsupported_fields_before_binding(self):
        with self.assertRaisesRegex(ValueError, "Unsupported installed C ABI"):
            structures("typedef struct Config { double unknown; } Config;", lambda _: True)
        types = structures("typedef struct Config { int32_t count; float scale; } Config;", lambda _: True)
        self.assertEqual(ctypes.sizeof(types["Config"]), 8)

    def test_library_binding_sets_namespace_and_signature_without_loading_a_dll(self):
        symbol = Mock()
        dll = Mock()
        dll.TestCreate = symbol
        with patch("scripts.launchers.shared.native_abi.native_library.ctypes.CDLL", return_value=dll):
            library = NativeLibrary(Path("fixture.dll"), prefix="Test")
            self.assertIs(library.bind("Create", [ctypes.c_int32], ctypes.c_void_p), symbol)
            self.assertEqual(symbol.argtypes, [ctypes.c_int32])
            self.assertIs(symbol.restype, ctypes.c_void_p)
            library.close()

    def test_shared_audio_conversion_preserves_channel_average_and_duration(self):
        import numpy as np

        from scripts.launchers.shared.media.audio import decode_audio, mono_resample, pcm_wav

        samples = np.tile(np.array([[0.25, 0.75]], dtype="float32"), (4800, 1))
        mono = mono_resample(samples, 48000)
        decoded, rate = decode_audio(pcm_wav(mono))
        self.assertEqual((rate, decoded.shape), (16000, (1600, 1)))
        self.assertAlmostEqual(float(decoded[800, 0]), 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
