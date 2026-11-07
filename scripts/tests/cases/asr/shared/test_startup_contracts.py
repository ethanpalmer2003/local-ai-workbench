"""The same safety contracts run against every reusable ASR server adapter."""

from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.launchers.asr.whispercpp import server as whisper
from scripts.launchers.asr.llamacpp import qwen3_asr, gemma_audio
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared.resident_profiles import profiles
from scripts.tests.shared.backend_fixtures import startup_fixture
from scripts.tests.shared.paths import CasePaths
from scripts.benchmarks.shared.resident_http import ResidentHttp

# Extend this matrix for reusable servers; keep isolated/in-process policies separate.
ADAPTERS = ((whisper, "WHISPERCPP_ASR"), (qwen3_asr, "QWEN3_ASR"), (gemma_audio, "GEMMA_AUDIO_ASR"))


class StartupContracts(unittest.TestCase):
    def test_matching_healthy_sessions_are_reused(self):
        with CasePaths(__file__).temporary_directory() as folder:
            for adapter, key in ADAPTERS:
                with self.subTest(adapter=key), startup_fixture(adapter, key, Path(folder)) as fixture:
                    fixture.ready.side_effect = None
                    fixture.ready.return_value = True
                    self.assertIsNone(adapter.start())
                    fixture.launch.assert_not_called()
                    fixture.stop.assert_not_called()

    def test_mismatched_or_occupied_sessions_are_preserved(self):
        with CasePaths(__file__).temporary_directory() as folder:
            for adapter, key in ADAPTERS:
                for healthy in (True, False):
                    with (
                        self.subTest(adapter=key, healthy=healthy),
                        startup_fixture(adapter, key, Path(folder)) as fixture,
                    ):
                        fixture.ready.side_effect = None
                        fixture.ready.return_value = healthy
                        fixture.matching.return_value = False
                        fixture.occupied.return_value = True
                        expected = "does not match" if healthy else "occupied"
                        with self.assertRaisesRegex(RuntimeError, expected):
                            adapter.start()
                        fixture.launch.assert_not_called()
                        fixture.stop.assert_not_called()

    def test_successful_startup_and_failed_owned_startup_cleanup(self):
        with CasePaths(__file__).temporary_directory() as folder:
            for adapter, key in ADAPTERS:
                for succeeds in (True, False):
                    with (
                        self.subTest(adapter=key, succeeds=succeeds),
                        startup_fixture(adapter, key, Path(folder)) as fixture,
                    ):
                        if succeeds:
                            self.assertIs(adapter.start(), fixture.worker)
                            fixture.stop.assert_not_called()
                            self.assertEqual(
                                fixture.launch.call_args.kwargs["mode"], cfg.ConsoleTerminalLaunchMode.MERGE
                            )
                            self.assertNotIn("kill_ports", fixture.launch.call_args.kwargs)
                        else:
                            fixture.ready.side_effect = [False, RuntimeError("fixture probe failed")]
                            with self.assertRaisesRegex(RuntimeError, "fixture probe failed"):
                                adapter.start()
                            fixture.stop.assert_called_once_with(fixture.worker.pid)
                            fixture.worker.wait.assert_called_once_with(timeout=15)

    def test_exited_owned_process_is_reaped_without_killing_a_reused_pid(self):
        with CasePaths(__file__).temporary_directory() as folder:
            for adapter, key in ADAPTERS:
                with self.subTest(adapter=key), startup_fixture(adapter, key, Path(folder)) as fixture:
                    fixture.worker.returncode = 1
                    with self.assertRaisesRegex(RuntimeError, "exited during startup"):
                        adapter.start()
                    fixture.stop.assert_not_called()
                    fixture.worker.wait.assert_called_once_with(timeout=15)

    def test_isolated_sessions_never_replace_an_existing_listener(self):
        with CasePaths(__file__).temporary_directory() as folder:
            for name, (command, model) in profiles(19123).items():
                if name == "sherpa-onnx":
                    continue  # This adapter is in-process, not an HTTP server.
                with (
                    self.subTest(engine=name),
                    patch("scripts.benchmarks.shared.resident_http.launch_util.llama_server_running", return_value=False),
                    patch("scripts.benchmarks.shared.resident_http.launch_util.port_listening", return_value=True),
                    patch("scripts.benchmarks.shared.resident_http.subprocess.Popen") as launch,
                    patch("scripts.benchmarks.shared.resident_http.stop_owned") as stop,
                ):
                    log = Path(folder) / f"{name}.log"
                    server = ResidentHttp(command, 19123, log, model_identity=str(model))
                    with self.assertRaisesRegex(RuntimeError, "occupied"), server.lifecycle as timer:
                        timer.prepare(server.start, combined=True)
                    launch.assert_not_called()
                    stop.assert_not_called()
                    self.assertFalse(log.exists())
