"""Default model-free regressions; `--suite` selects native launcher or backend checks."""

from __future__ import annotations

import argparse
import base64
import contextlib
import importlib.metadata
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import unittest
import urllib.error
import urllib.request
import wave
from dataclasses import replace
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.benchmarks.shared.reporting import RunReport
from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_cfg
from scripts.launchers import launch_util, proxy_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp, audiocpp_catalog, audiocpp_proxy, tts_proxy, tts_text_processing
from scripts.launchers.koboldcpp import kobold
from scripts.launchers.llamacpp import llamacpp, llamacpp_coding, llamacpp_dsh, llamacpp_littlecoder
from scripts.launchers.sdcpp import proxy as sdcpp_proxy
from scripts.launchers.sdcpp import server as sdcpp
from scripts.shared.http_server import request, server
from scripts.tests.cases.suites import live_frameworks, quick_validation
from scripts.tests.cases.suites.launcher_behaviors import LauncherBehaviors
from scripts.tests.shared.media_fixtures import PNG, wav_fixture
from scripts.tests.shared.model_checks import requires_model_check
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.process_fixtures import exited_process, running_process
from scripts.tests.shared.timing import timed


@requires_model_check
class DefaultPaths(unittest.TestCase):
    def test_venv_and_lock(self):
        if not project_cfg.VENV_DIR.is_dir():
            self.skipTest("this checkout has no virtual environment")
        self.assertEqual(Path(sys.prefix).resolve(), project_cfg.VENV_DIR.resolve())
        self.assertEqual(sys.version_info[:2], (3, 13))
        lock = tomllib.loads((project_cfg.BASE_DIR / "uv.lock").read_text(encoding="utf-8"))
        for entry in lock.get("package", []):
            name, version = entry.get("name"), entry.get("version")
            if not name or not version:
                continue
            try:
                installed_version = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                continue
            with self.subTest(package=name):
                self.assertEqual(installed_version, version)

    def test_sdcpp_default_files(self):
        for path in (sdcpp.build_dir() / "sd-server.exe", Path(str(cfg.SDCPP_SERVER_ARGS["m"]))):
            self.assertTrue(path.is_file(), str(path))
        self.assertTrue(Path(cfg.SDCPP_LORA_DIR).is_dir(), cfg.SDCPP_LORA_DIR)

    def test_audiocpp_default_files_and_voice(self):
        self.assertTrue(project_cfg.AUDIOCPP_SERVER_EXE.is_file())
        config = audio_cfg.read(Path(cfg.AUDIOCPP_SERVER_ARGS["config"]))
        models = [model for model in config["models"] if model["id"] == cfg.AUDIOCPP_SERVICE.model]
        self.assertEqual(len(models), 1, "default audio model must exist in server.json")
        self.assertTrue(Path(models[0]["path"]).is_file(), models[0]["path"])
        # - a configured default voice must resolve to a clip reference; with none, cloning stays off
        reference = audiocpp_catalog.resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
        if cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value:
            self.assertIsNotNone(reference, "configured default voice has no reference clip")
        else:
            self.assertIsNone(reference)

    def test_llamacpp_coding_default_files(self):
        conf = llamacpp.LlamaConfig()
        for path in (conf.exe, conf.model, conf.ini_path, cfg.LITTLECODER_CLIENT.entry, cfg.PI_CLIENT.entry):
            self.assertTrue(path.is_file(), str(path))
        self.assertIsNotNone(shutil.which(cfg.PI_CLIENT.node_cmd), "Node missing from PATH")
        self.assertTrue(conf.get_ini(), "default INI is empty or unreadable")

    def test_kobold_default_files(self):
        for path in (cfg.KOBOLDCPP_SERVICE.exe, cfg.KOBOLDCPP_SERVICE.config, cfg.kobold_chat_model_path()):
            self.assertTrue(path.is_file(), str(path))

    def test_dsh_default_files(self):
        for path in (cfg.DEEPSEEK_CLIENT.exe, cfg.DEEPSEEK_CLIENT.patch_path()):
            self.assertTrue(path.is_file(), str(path))


class DefaultPorts(unittest.TestCase):
    """Port ownership is this repository's config, so it runs without a model check."""

    def test_ports_are_distinct(self):
        ports = [cfg.LLAMACPP_SERVICE.port, cfg.LLAMACPP_SERVICE.internal_port, live_frameworks.kobold_port()]
        for service in (cfg.SDCPP_SERVICE, cfg.AUDIOCPP_SERVICE):
            ports.extend((service.port, service.internal_port))
        self.assertEqual(len(ports), len(set(ports)), "default ports collide")


class LaunchCommands(unittest.TestCase):
    def test_llama_warmup_after_readiness(self):
        conf = llamacpp.LlamaConfig()
        with (
            patch.object(llamacpp, "launch_process", autospec=True) as spawn,
            patch.object(llamacpp, "LlamaMonitor", autospec=True) as monitor,
            patch.object(llamacpp, "trigger_preload", autospec=True) as preload,
            patch.object(llamacpp, "kill_process_tree"),
        ):
            monitor.return_value.log_file = CasePaths(__file__).new_run().temp / "warmup-regression-unused.log"
            monitor.return_value.wait_ready.return_value = True
            llamacpp.launch(conf=conf)
            cmd = spawn.call_args.args[0]
            self.assertIn("scripts.launchers.llamacpp.llamacpp_terminal", cmd)
            self.assertNotIn("report_vram", spawn.call_args.kwargs)
            self.assertEqual(preload.call_args.kwargs["url"], cfg.llama_base_url(conf.port) + "/chat/completions")
            self.assertEqual(preload.call_args.kwargs["payload"]["model"], conf.alias)
            self.assertEqual(preload.call_args.kwargs["payload"]["max_tokens"], 1)
            self.assertFalse(preload.call_args.kwargs["background"])
            preload.reset_mock()
            monitor.return_value.wait_ready.return_value = False
            with self.assertRaises(TimeoutError):
                llamacpp.launch(conf=conf)
            preload.assert_not_called()

    def test_sdcpp_backend_port_and_extra_args(self):
        with patch.object(sdcpp, "launch_process", autospec=True) as spawn:
            sdcpp.launch(port=cfg.SDCPP_SERVICE.internal_port, extra_args=["--threads", "2"])
        cmd = spawn.call_args.args[0]
        self.assertEqual(cmd[0], str(sdcpp.build_dir() / "sd-server.exe"))
        self.assertEqual(cmd[cmd.index("--listen-port") + 1], str(cfg.SDCPP_SERVICE.internal_port))
        self.assertEqual(cmd[-2:], ["--threads", "2"])
        self.assertTrue(spawn.call_args.kwargs["env"]["PATH"].startswith(str(sdcpp.build_dir())))

    def test_sdcpp_vulkan_selection_does_not_inject_rocm_runtime(self):
        with patch.object(sdcpp, "launch_process", autospec=True) as spawn:
            sdcpp.launch(extra_args=["--build", "vulkan", "--threads", "2"])
        command = spawn.call_args.args[0]
        self.assertEqual(command[0], str(cfg.SDCPP_BUILDS["vulkan"] / "sd-server.exe"))
        self.assertNotIn("--build", command)
        self.assertEqual(command[-2:], ["--threads", "2"])
        self.assertTrue(spawn.call_args.kwargs["env"]["PATH"].startswith(str(cfg.SDCPP_BUILDS["vulkan"])))

    def test_sdcpp_q4_profile_selects_actual_file_and_runtime_label(self):
        original = cfg.SDCPP_SERVICE.model
        with (
            patch.object(cfg, "SDCPP_SERVICE", replace(cfg.SDCPP_SERVICE)),
            patch.object(sdcpp, "launch_process", autospec=True) as spawn,
        ):
            sdcpp.launch(extra_args=["--model-profile", "nova3d-q4"])
            command = spawn.call_args.args[0]
            self.assertNotIn("--model-profile", command)
            self.assertEqual(command[command.index("-m") + 1], cfg.SDCPP_MODELS["nova3d-q4"])
            self.assertEqual(cfg.SDCPP_SERVICE.model, "nova3d-q4")
        self.assertEqual(cfg.SDCPP_SERVICE.model, original)

    def test_audio_backend_port_and_default_model(self):
        with patch.object(audiocpp, "launch_process", autospec=True) as spawn:
            audiocpp.launch(port=cfg.AUDIOCPP_SERVICE.internal_port, report_vram=False)
        cmd = spawn.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--port") + 1], str(cfg.AUDIOCPP_SERVICE.internal_port))
        self.assertEqual(cmd[cmd.index("--model") + 1], cfg.AUDIOCPP_SERVICE.model)
        self.assertFalse(spawn.call_args.kwargs["report_vram"])

    def test_sdcpp_proxy_wiring(self):
        with contextlib.ExitStack() as stack:
            kill = stack.enter_context(patch.object(sdcpp_proxy, "prepare_service_port", autospec=True))
            backend = stack.enter_context(patch.object(sdcpp, "launch", autospec=True))
            stack.enter_context(patch.object(sdcpp_proxy, "_trigger_sdcpp_preload", autospec=True))
            proxy = stack.enter_context(patch.object(sdcpp_proxy, "run_json_proxy", autospec=True))
            stack.enter_context(patch.object(sys, "argv", ["sdcpp_proxy"]))
            sdcpp_proxy.launch_proxy()
        kill.assert_called_once_with(cfg.SDCPP_SERVICE.port, "SdCpp Proxy")
        self.assertEqual(backend.call_args.kwargs["port"], cfg.SDCPP_SERVICE.internal_port)
        self.assertEqual(proxy.call_args.args[1], f"http://127.0.0.1:{cfg.SDCPP_SERVICE.internal_port}")
        self.assertIs(proxy.call_args.kwargs["on_response"], sdcpp.save_generated_images)

    def test_audio_proxy_wiring(self):
        with contextlib.ExitStack() as stack:
            kill = stack.enter_context(patch.object(audiocpp_proxy, "prepare_service_port", autospec=True))
            backend = stack.enter_context(patch.object(audiocpp, "launch", autospec=True))
            stack.enter_context(patch.object(audiocpp_proxy, "get_gpu_memory_snapshot", autospec=True))
            stack.enter_context(patch.object(audiocpp_proxy, "_trigger_audiocpp_preload", autospec=True))
            proxy = stack.enter_context(patch.object(audiocpp_proxy, "run_tts_json_proxy", autospec=True))
            stack.enter_context(patch.object(sys, "argv", ["audiocpp_proxy"]))
            audiocpp_proxy.launch_proxy()
        kill.assert_called_once_with(cfg.AUDIOCPP_SERVICE.port, "AudioCpp Proxy")
        self.assertEqual(backend.call_args.kwargs["port"], cfg.AUDIOCPP_SERVICE.internal_port)
        self.assertEqual(proxy.call_args.args[1], f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}")
        self.assertIs(proxy.call_args.kwargs["transform"], audiocpp_proxy._transform)

    def test_llama_ini_overrides_and_alias(self):
        conf = llamacpp.LlamaConfig(ini_overrides={"ctx-size": "4096", "temperature": "0.25"})
        cmd = conf.build_cmd(llamacpp.DRY_RUN_LOG_FILE)
        self.assertEqual(cmd[cmd.index("--alias") + 1], conf.model.stem)
        self.assertEqual(cmd[cmd.index("--temperature") + 1], "0.25")
        self.assertEqual(cmd[cmd.index("--ctx-size") + 1], "4096")

    def test_pi_default_client_command(self):
        with CasePaths(__file__).temporary_directory() as folder, contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(cfg, "PI_CLIENT", replace(cfg.PI_CLIENT, agent_dir=Path(folder) / "agent"))
            )
            stack.enter_context(patch.object(llamacpp, "launch", autospec=True))
            run = stack.enter_context(patch.object(llamacpp_coding.subprocess, "run", autospec=True))
            stack.enter_context(patch.object(sys, "argv", ["llamacpp_coding"]))
            llamacpp_coding.main()
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[:2], [cfg.PI_CLIENT.node_cmd, str(cfg.PI_CLIENT.entry)])
            self.assertEqual(cmd[cmd.index("--model") + 1], llamacpp.LlamaConfig().alias)
            settings = json.loads((cfg.PI_CLIENT.agent_dir / "settings.json").read_text(encoding="utf-8"))
            self.assertIn("+codemode", settings["defaultTools"])
            self.assertIn(cfg.PI_CLIENT.packages[0].as_posix(), settings["packages"])
            self.assertEqual(run.call_args.kwargs["cwd"], project_cfg.BASE_DIR)
            self.assertEqual(run.call_args.kwargs["env"]["PI_CODING_AGENT_DIR"], str(cfg.PI_CLIENT.agent_dir))
            self.assertTrue(run.call_args.kwargs["check"])

    def test_littlecoder_default_client_command(self):
        with CasePaths(__file__).temporary_directory() as folder, contextlib.ExitStack() as stack:
            client = replace(cfg.LITTLECODER_CLIENT, agent_dir=Path(folder) / "agent")
            stack.enter_context(patch.object(cfg, "LITTLECODER_CLIENT", client))
            stack.enter_context(patch.object(llamacpp, "launch", autospec=True))
            run = stack.enter_context(patch.object(llamacpp_coding.subprocess, "run", autospec=True))
            stack.enter_context(patch.object(sys, "argv", ["llamacpp_littlecoder", "--", "-p", "hello"]))
            llamacpp_littlecoder.main()
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[:2], [client.node_cmd, str(client.entry)])
            self.assertEqual(cmd[-2:], ["-p", "hello"])
            self.assertEqual(run.call_args.kwargs["env"]["PI_CODING_AGENT_DIR"], str(client.agent_dir))

    def test_kobold_native_config_and_cli_launch(self):
        original = cfg.KOBOLDCPP_SERVICE.config.read_bytes()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(kobold, "LOG_DIR", Path(folder)),
            patch.object(project_cfg, "GENERATED_DIR", Path(folder) / "generated"),
            patch.object(kobold, "launch_process", autospec=True) as spawn,
        ):
            _, config_path, _ = kobold.start_kobold()
            command = spawn.call_args.args[0]
            self.assertEqual(config_path, cfg.KOBOLDCPP_SERVICE.config)
            generated = Path(command[command.index("--config") + 1])
            self.assertEqual(
                generated, Path(folder) / "generated" / "shared" / "configs" / cfg.KOBOLDCPP_SERVICE.config.name
            )
            self.assertNotIn("{AI_ROOT}", generated.read_text(encoding="utf-8"))
            self.assertEqual(command[command.index("--model") + 1], str(cfg.kobold_chat_model_path()))
            self.assertEqual(command[command.index("--port") + 1], str(cfg.KOBOLDCPP_KCPPS_ARGS["port"]))
            self.assertEqual(command[command.index("--usevulkan") + 1], "0")
            # - the character stack asks for no transcription, so the built-in Whisper weight stays off
            self.assertNotIn("--whispermodel", command)
            self.assertEqual(cfg.KOBOLDCPP_SERVICE.config.read_text(encoding="utf-8").count('"whispermodel": ""'), 1)
            self.assertNotIn("--cli", command)
            self.assertTrue((Path(folder) / "generated").exists())
        self.assertEqual(cfg.KOBOLDCPP_SERVICE.config.read_bytes(), original)

    def test_kobold_admin_password_comes_from_environment(self):
        with patch.object(cfg, "KOBOLDCPP_ADMIN_PASSWORD", "local-secret"):
            command = kobold.server_command()
            self.assertEqual(command[command.index("--adminpassword") + 1], "local-secret")
        with patch.object(cfg, "KOBOLDCPP_ADMIN_PASSWORD", ""):
            self.assertNotIn("--adminpassword", kobold.server_command())

    def test_kobold_external_transcription_omits_whispermodel_flag(self):
        engines = (
            cfg.AsrStartupEngine.AUDIOCPP,
            cfg.AsrStartupEngine.NEMO,
            cfg.AsrStartupEngine.WHISPER_VULKAN,
            cfg.AsrStartupEngine.QWEN3_ASR,
            cfg.AsrStartupEngine.PARAKEET_V3,
        )
        for engine in engines:
            with self.subTest(engine=engine), patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", engine):
                command = kobold.server_command()
                self.assertNotIn("--whispermodel", command)
                for index, token in enumerate(command):
                    if token.startswith("--") and index + 1 < len(command):
                        self.assertNotEqual(command[index + 1], "", f"{token} has an empty value")

    def test_kobold_without_a_transcription_engine_loads_no_whisper_model(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", None):
            command = kobold.server_command()
        self.assertNotIn("--whispermodel", command)

    def test_kobold_embedded_engine_keeps_the_built_in_whisper_model(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.EMBEDDED):
            command = kobold.server_command()
        self.assertEqual(command[command.index("--whispermodel") + 1], str(cfg.KOBOLDCPP_KCPPS_ARGS["whispermodel"]))

    def test_kobold_opens_localhost_proxy_only_after_page_is_ready(self):
        with (
            patch.object(kobold, "backend_ready", side_effect=[False, True, True]) as probe,
            patch.object(kobold.time, "sleep"),
            patch.object(kobold, "open_browser") as browser,
        ):
            kobold.open_streaming_ui()
        url = f"http://localhost:{cfg.KOBOLDCPP_SERVICE.streaming_ui_port}"
        backend_url = f"http://127.0.0.1:{cfg.KOBOLDCPP_KCPPS_ARGS['port']}/"
        self.assertEqual([call.args[0] for call in probe.call_args_list], [backend_url, backend_url, url])
        browser.assert_called_once_with(url)

    def test_kobold_without_proxy_preserves_native_browser_setting(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "streaming_ui", False):
            command = kobold.server_command()
        self.assertNotIn("--launch", command)
        self.assertNotIn("--cli", command)

    def test_kobold_main_does_not_remove_native_base_on_exit(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "base.kcpps"
            path.write_text("{}", encoding="utf-8")
            process = exited_process()
            with (
                patch.object(kobold, "start_kobold", return_value=(process, path, Path(folder) / "log")),
                patch.object(kobold, "print_summary"),
                patch.object(kobold.time, "sleep"),
                patch.object(cfg.KOBOLDCPP_SERVICE, "streaming_ui", False),
                patch.object(cfg.KOBOLDCPP_SERVICE, "model", cfg.KOBOLDCPP_SERVICE.model),
                patch.object(cfg.AUDIOCPP_SERVICE, "enabled", False),
                patch.object(cfg.SDCPP_SERVICE, "enabled", False),
            ):
                kobold.main(["--model", "llamacpp/gemma-4-E4B-it-Q4_0"])
                command = kobold.server_command("shared")
                self.assertEqual(
                    command[command.index("--model") + 1],
                    str(project_cfg.LLMS_MULTILINGUAL_MODELS_DIR / "gemma-4-E4B-it-Q4_0.gguf"),
                )
                self.assertNotIn("--whispermodel", command)
            self.assertEqual(path.read_text(), "{}")

    def test_spawn_environment_and_extra_args(self):
        process = running_process(pid=12345)
        with patch.object(launch_util.subprocess, "Popen", autospec=True, return_value=process) as spawn:
            launch_util.launch_module(
                "scripts.launchers.audiocpp.audiocpp_proxy",
                "test",
                mode=cfg.ConsoleTerminalLaunchMode.SPLIT_INDEPENDENT,
                extra_args=["--threads", "2"],
            )
        cmd = spawn.call_args.args[0]
        if sys.platform == "win32":
            self.assertEqual(cmd[:4], ["powershell.exe", "-NoProfile", "-NoExit", "-Command"])
            self.assertTrue(cmd[-1].endswith("'--threads' '2'"))
        else:
            self.assertEqual(cmd[-2:], ["--threads", "2"])
        for name in ("TEMP", "TMP", "TMPDIR"):
            self.assertEqual(spawn.call_args.kwargs["env"][name], str(cfg.LAUNCH.temp_dir))

    def test_live_worker_uses_existing_launchers(self):
        for name, module in (
            ("sdcpp", sdcpp_proxy),
            ("audiocpp", audiocpp_proxy),
            ("llamacpp", llamacpp_coding),
            ("kobold", kobold),
            ("dsh", llamacpp_dsh),
        ):
            with (
                self.subTest(framework=name),
                patch.object(module, "main", autospec=True) as launch,
                patch.object(cfg.LAUNCH, "console_terminal_mode"),
                patch.object(sys, "argv", ["test"]),
                patch.object(launch_util, "kill_processes_on_ports"),
            ):
                live_frameworks.launch_worker(name)
                launch.assert_called_once_with()
                self.assertEqual(cfg.LAUNCH.console_terminal_mode, cfg.ConsoleTerminalLaunchMode.MERGE)
                self.assertEqual(sys.argv[1:], ["--client", "none"] if name == "llamacpp" else [])

    def test_merge_logging_launches_executable_directly(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "backend.log"
            process = running_process(pid=12345)
            with (
                patch.object(launch_util.subprocess, "Popen", autospec=True, return_value=process) as spawn,
                patch.object(launch_util, "assign_process_to_job"),
            ):
                launch_util.launch_process(
                    ["backend.exe", "--config", "test.json"],
                    "test",
                    mode=cfg.ConsoleTerminalLaunchMode.MERGE,
                    log_file=str(path),
                )
            self.assertEqual(spawn.call_args.args[0], ["backend.exe", "--config", "test.json"])
            self.assertEqual(spawn.call_args.kwargs["stdout"].name, str(path))
            self.assertIs(spawn.call_args.kwargs["stdout"], spawn.call_args.kwargs["stderr"])

    @unittest.skipUnless(sys.platform == "win32", "Windows job-object lifecycle")
    @fixture_processes()
    def test_kill_on_close_job_stops_descendants(self):
        import psutil

        code = (
            "import os, subprocess, sys; from scripts.launchers import launch_util; "
            "launch_util.assign_process_to_job(os.getpid()); "
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "print(child.pid, flush=True); sys.stdin.buffer.read()"
        )
        worker = subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=project_cfg.BASE_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        child_pid = None
        try:
            assert worker.stdout is not None and worker.stdin is not None
            child_pid = int(worker.stdout.readline().strip())
            worker.stdin.close()
            worker.wait(timeout=5)
            self.assertEqual(worker.returncode, 0)
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(child_pid).wait(timeout=5)
            self.assertFalse(psutil.pid_exists(child_pid), "worker job left its child process running")
        finally:
            # - harmless fixture processes only; no production ports are touched
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=5)
            if child_pid is not None and psutil.pid_exists(child_pid):
                psutil.Process(child_pid).kill()
                psutil.Process(child_pid).wait(timeout=5)
            for pipe in (worker.stdin, worker.stdout, worker.stderr):
                if pipe is not None:
                    pipe.close()


class StateAndReadiness(unittest.TestCase):
    def test_readiness_only_suppresses_expected_backend_unavailability(self):
        expected = [
            urllib.error.URLError(ConnectionRefusedError()),
            TimeoutError(),
            urllib.error.HTTPError("test", 502, "loading", Mock(), None),
            urllib.error.HTTPError("test", 503, "loading", Mock(), None),
        ]
        unexpected = [
            ValueError("bad configuration"),
            PermissionError("denied"),
            urllib.error.URLError("invalid hostname"),
            urllib.error.HTTPError("test", 404, "wrong endpoint", Mock(), None),
            urllib.error.HTTPError("test", 500, "backend bug", Mock(), None),
        ]
        for error in expected + unexpected:
            with self.subTest(error=error), patch.object(launch_util.urllib.request, "urlopen", side_effect=error):
                if error in expected:
                    self.assertFalse(launch_util.backend_ready("http://backend/health"))
                else:
                    with self.assertRaises(type(error)):
                        launch_util.backend_ready("http://backend/health")

    def test_warmup_unexpected_errors_propagate(self):
        with (
            patch.object(launch_util.urllib.request, "urlopen", side_effect=ValueError("bad request")),
            self.assertRaisesRegex(ValueError, "bad request"),
        ):
            launch_util.trigger_preload(True, "test", "http://backend/speech", {}, background=False)

    def test_warmup_waits_for_backend_and_drains_response_before_success(self):
        health = Mock()
        audio = Mock()
        audio.read.side_effect = [b"first", b"last", b""]
        health_context = Mock()
        health_context.__enter__ = Mock(return_value=health)
        health_context.__exit__ = Mock(return_value=False)
        audio_context = Mock()
        audio_context.__enter__ = Mock(return_value=audio)
        audio_context.__exit__ = Mock(return_value=False)

        def completed():
            self.assertEqual(audio.read.call_count, 3)

        with (
            patch.object(
                launch_util.urllib.request,
                "urlopen",
                side_effect=[urllib.error.URLError(ConnectionRefusedError()), health_context, audio_context],
            ) as opened,
            patch.object(launch_util.time, "sleep"),
        ):
            launch_util.trigger_preload(
                True, "test", "http://proxy/speech", {}, completed, background=False, ready_url="http://backend/health"
            )
        self.assertEqual(
            [call.args[0] for call in opened.call_args_list[:2]], ["http://backend/health", "http://backend/health"]
        )
        self.assertEqual(opened.call_args.args[0].full_url, "http://proxy/speech")

    def test_dsh_attaches_to_existing_server(self):
        with (
            patch.object(sys, "argv", ["llamacpp_dsh", "--no-open"]),
            patch.object(llamacpp_dsh, "backend_running", return_value=True),
            patch.object(llamacpp, "launch", autospec=True) as launch,
        ):
            self.assertEqual(llamacpp_dsh.main(), 0)
            launch.assert_not_called()

    def test_dsh_patch_preserves_other_entries_and_is_stable(self):
        original = "# Custom entry\n- id: custom\n  config: !!js process.env.CUSTOM\n"
        block = llamacpp_dsh.render_entry(["model: quoted # id"], cfg.LLAMACPP_SERVICE.port)
        updated = llamacpp_dsh.upsert_entry(original, block)
        self.assertTrue(updated.startswith(original))
        self.assertEqual(llamacpp_dsh.upsert_entry(updated, block), updated)
        self.assertEqual(updated.count("- id: llm-pi-ai\n"), 1)

    def test_pi_migration_preserves_local_changes(self):
        with CasePaths(__file__).temporary_directory() as folder:
            old, new = Path(folder) / "old", Path(folder) / "new"
            (old / "sessions").mkdir(parents=True)
            (old / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
            (old / "sessions" / "history.jsonl").write_text("history", encoding="utf-8")
            with (
                patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(old), "LITTLE_CODER_BASH_ALLOW": "custom-command"}),
                patch.object(cfg, "PI_CLIENT", replace(cfg.PI_CLIENT, agent_dir=new)),
            ):
                env = llamacpp_coding.prepare_pi_env()
                self.assertIn("custom-command", env["LITTLE_CODER_BASH_ALLOW"])
                self.assertEqual((new / "sessions" / "history.jsonl").read_text(), "history")
                (new / "settings.json").write_text('{"theme":"light"}', encoding="utf-8")
                llamacpp_coding.prepare_pi_env()
                self.assertEqual(json.loads((new / "settings.json").read_text())["theme"], "light")
                self.assertEqual(os.environ["PI_CODING_AGENT_DIR"], str(old))
                for extension in cfg.PI_CLIENT.extensions:
                    self.assertEqual((new / "extensions" / extension.name).read_bytes(), extension.read_bytes())

    def test_health_polling_waits_for_real_success(self):
        with patch.object(launch_util, "backend_running", side_effect=[False, False, True]) as health:
            self.assertTrue(launch_util.wait_for_backend(12345, 1, interval_s=0))
            self.assertEqual(health.call_count, 3)
        self.assertFalse(launch_util.wait_for_backend(12345, 0))

    @requires_model_check
    def test_deepseek_launch_environment(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(cfg, "DEEPSEEK_CLIENT", replace(cfg.DEEPSEEK_CLIENT, home=Path(folder) / "state")),
        ):
            env = llamacpp_dsh.prepare_dsh_env()
            self.assertEqual(env["DSH_HOME"], str(cfg.DEEPSEEK_CLIENT.home))
            self.assertTrue(cfg.DEEPSEEK_CLIENT.patch_path().is_file())

    def test_dsh_wrapper_does_not_open_desktop(self):
        with (
            patch.object(sys, "argv", ["llamacpp_dsh"]),
            patch.object(llamacpp_dsh, "prepare_dsh_env"),
            patch.object(llamacpp_dsh, "backend_running", return_value=True),
            patch.object(subprocess, "Popen", autospec=True) as spawn,
        ):
            self.assertEqual(llamacpp_dsh.main(), 0)
            spawn.assert_not_called()


class ProxyHTTP(unittest.TestCase):
    def test_model_default_refresh_passes_selected_model_to_catalog(self):
        snapshot = {
            "selected_model": cfg.AudiocppModel.FISH_DRAMA3_Q2.value,
            "packaged_defaults": {"request": {"temperature": 0.8}},
        }
        with patch.object(audiocpp_catalog, "runtime_defaults", return_value=snapshot) as defaults:
            status, body, _ = request(self.audio_url + f"/proxy/config?model={cfg.AudiocppModel.FISH_DRAMA3_Q2.value}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), snapshot)
        defaults.assert_called_once_with(cfg.AUDIOCPP_SERVICE, cfg.AudiocppModel.FISH_DRAMA3_Q2.value)

    def test_comparison_catalog_is_served_locally(self):
        catalog = {"voices": [{"id": "voice-a", "available": True}], "models": []}
        with patch.object(audiocpp_catalog, "comparison_catalog", return_value=catalog):
            status, body, _ = request(self.audio_url + "/proxy/comparison-catalog")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), catalog)
        self.assertEqual(self.requests, [])

    def test_invalid_comparison_returns_400_without_generating_a_default(self):
        with patch.object(audiocpp_catalog, "configured_models", return_value=[]):
            status, body, _ = request(
                self.audio_url + "/v1/audio/speech",
                {"input": "test", "model": "missing", "voice": "voice-a", "_comparison": True, "stream": False},
            )
        self.assertEqual(status, 400)
        self.assertIn("no fallback was used", body.decode())
        self.assertEqual(self.requests, [])

    def test_comparison_generates_wav_with_exact_voice_and_model(self):
        with (
            patch.object(cfg, "AUDIOCPP_PROXY_CLONE_VOICES", ("voice-a",)),
            patch.object(
                audiocpp_catalog,
                "configured_models",
                return_value=[{"id": cfg.AudiocppModel.BREEZE_TTS.value, "installed": True, "clone": True}],
            ),
            patch.object(audiocpp_catalog, "resolve_voice_ref", return_value=("voice-a.wav", "reference")),
        ):
            status, body, _ = request(
                self.audio_url + "/v1/audio/speech",
                {
                    "input": "Hello",
                    "model": cfg.AudiocppModel.BREEZE_TTS.value,
                    "voice": "voice-a",
                    "_comparison": True,
                },
            )
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"RIFF"))
        forwarded = self.requests[-1]
        self.assertEqual(forwarded["model"], cfg.AudiocppModel.BREEZE_TTS.value)
        self.assertEqual(forwarded["voice"], "voice-a")
        self.assertEqual(forwarded["voice_ref"], "voice-a.wav")
        self.assertNotIn("_comparison", forwarded)

    def test_test_page_reads_current_proxy_defaults(self):
        status, body, _ = request(self.audio_url + "/proxy/config")
        data = json.loads(body)
        self.assertEqual(status, 200)
        preset = cfg.AUDIOCPP_PROXY_MODEL_PRESETS.get(cfg.AudiocppModel(cfg.AUDIOCPP_SERVICE.model))
        expected_buffer = (
            preset.playback_buffer_ms
            if preset and preset.playback_buffer_ms is not None
            else cfg.AUDIOCPP_SERVICE.streaming.playback_buffer_ms
        )
        self.assertEqual(data["streaming"]["playback_buffer_ms"], expected_buffer)
        self.assertEqual(data["playback_note"], preset.playback_note if preset else "")
        self.assertEqual(data["streaming"]["pcm_sample_rate"], cfg.AUDIOCPP_SERVICE.streaming.pcm_sample_rate)
        self.assertEqual(data["model"], cfg.AUDIOCPP_SERVICE.model)

    def __init__(self, methodName: str = "runTest"):
        super().__init__(methodName)
        self.stack = contextlib.ExitStack()
        self.requests: list[dict[str, object]] = []
        self.image_dir = Path()
        self.sd_url = ""
        self.audio_url = ""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", False))
        self.requests = []
        calls = self.requests

        class Backend(BaseHTTPRequestHandler):
            def do_GET(self):
                proxy_util.send_bytes(self, 200, b'{"status":"ok"}', "application/json")

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                calls.append(payload)
                if self.path == "/fail":
                    proxy_util.send_bytes(self, 422, b'{"error":"fixture failure"}', "application/json")
                elif self.path == "/v1/audio/speech":
                    proxy_util.send_bytes(self, 200, wav_fixture(), "audio/wav")
                else:
                    image = {"data": [{"b64_json": base64.b64encode(PNG).decode("ascii")}]}
                    proxy_util.send_bytes(self, 200, json.dumps(image).encode(), "application/json")

            def log_message(self, format: str, *args: object):
                pass

        upstream = self.stack.enter_context(server(Backend))
        folder = self.stack.enter_context(CasePaths(__file__).temporary_directory())
        self.image_dir = Path(folder) / "images"
        self.stack.enter_context(patch.object(cfg, "SDCPP_OUTPUT_DIR", str(self.image_dir)))
        self.stack.enter_context(patch.object(tts_text_processing, "tone_state", tts_text_processing.ToneState()))
        with patch.object(proxy_util, "serve_proxy", autospec=True) as serve:
            proxy_util.run_json_proxy(
                cfg.SDCPP_SERVICE, upstream, transform=sdcpp_proxy._transform, on_response=sdcpp.save_generated_images
            )
        self.sd_url = self.stack.enter_context(server(serve.call_args.args[0]))
        with patch.object(tts_proxy, "serve_proxy", autospec=True) as serve:
            tts_proxy.run_tts_json_proxy(cfg.AUDIOCPP_SERVICE, upstream, transform=audiocpp_proxy._transform)
        self.audio_url = self.stack.enter_context(server(serve.call_args.args[0]))

    def test_image_generation_forwarding_and_saving(self):
        status, body, _ = request(
            self.sd_url + "/v1/images/generations",
            {"prompt": "a red cube", "model": "unknown", "steps": 1, "width": 256},
        )
        self.assertEqual(status, 200)
        self.assertIn("data", json.loads(body))
        forwarded = self.requests[-1]
        self.assertEqual(forwarded["model"], cfg.SDCPP_SERVICE.model)
        self.assertEqual(forwarded["steps"], 1)
        self.assertEqual(forwarded["width"], 256)
        self.assertEqual(forwarded["size"], f"256x{cfg.SDCPP_REQUEST_DEFAULTS['height']}")
        native = json.loads(str(forwarded["prompt"]).split("<sd_cpp_extra_args>")[1].split("</sd_cpp_extra_args>")[0])
        self.assertEqual(native["sample_params"]["sample_steps"], 1)
        self.assertEqual(native["negative_prompt"], cfg.SDCPP_REQUEST_DEFAULTS["negative_prompt"])
        self.assertIn("a red cube", str(forwarded["prompt"]))
        self.assertEqual(forwarded["negative_prompt"], cfg.SDCPP_REQUEST_DEFAULTS["negative_prompt"])
        files = list(self.image_dir.glob("*.png"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG)

    def test_image_preload_is_not_saved_or_forwarded(self):
        self.assertEqual(
            request(self.sd_url + "/v1/images/generations", {"prompt": "cube", "_skip_save": True})[0], 200
        )
        self.assertNotIn("_skip_save", self.requests[-1])
        self.assertFalse(self.image_dir.exists())

    def test_image_invalid_json_returns_400(self):
        self.assertEqual(request(self.sd_url + "/v1/images/generations", b"{bad json")[0], 400)
        self.assertFalse(self.requests)

    def test_upstream_error_is_preserved(self):
        status, body, _ = request(self.sd_url + "/fail", {"prompt": "cube"})
        self.assertEqual(status, 422)
        self.assertIn("fixture failure", json.loads(body)["error"])

    def test_audio_default_voice_and_wav(self):
        status, body, content_type = request(
            self.audio_url + "/v1/audio/speech",
            {"input": "This is a short test.", "voice": "unknown", "model": "unknown"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "audio/wav")
        with wave.open(io.BytesIO(body), "rb") as wav:
            self.assertGreater(wav.getnframes(), 0)
            self.assertEqual(wav.getframerate(), 16000)
        forwarded = self.requests[-1]
        self.assertEqual(forwarded["model"], cfg.AUDIOCPP_SERVICE.model)
        # - an unknown clone id falls back to the configured default, which may be empty
        self.assertEqual(forwarded["voice"], cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
        self.assertEqual(
            "voice_ref" in forwarded, bool(audiocpp_catalog.resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value))
        )

    def test_audio_unicode_input_survives_logging_and_forwarding(self):
        text = "Hello, \u4e16\u754c."
        status, _, _ = request(self.audio_url + "/v1/audio/speech", {"input": text})
        self.assertEqual(status, 200)
        self.assertIn("\u4e16\u754c", str(self.requests[-1]["input"]))

    def test_audio_invalid_and_skipped_requests_do_not_stall_next_request(self):
        with patch.object(tts_proxy, "read_request_body", side_effect=ValueError("invalid Content-Length")):
            self.assertEqual(request(self.audio_url + "/v1/audio/speech", {"input": "bad read"})[0], 500)
        self.assertEqual(request(self.audio_url + "/v1/audio/speech", b"{bad json")[0], 400)
        self.assertEqual(request(self.audio_url + "/v1/audio/speech", {"input": ""})[0], 204)
        self.assertEqual(
            request(self.audio_url + "/v1/audio/speech", {"input": "This request should succeed."})[0], 200
        )

    def test_health_get_passes_through_both_proxies(self):
        for url in (self.sd_url, self.audio_url):
            with self.subTest(proxy=url):
                self.assertEqual(request(url + "/health")[0], 200)

    def test_complete_wav_preserves_upstream_audio_bytes(self):
        status, body, content_type = request(
            self.audio_url + "/v1/audio/speech", {"input": "Hello", "stream": False, "response_format": "wav"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "audio/wav")
        self.assertEqual(body, wav_fixture())

    def test_audio_stream_arrives_before_generation_finishes(self):
        finish = threading.Event()

        class StreamingBackend(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "audio/pcm")
                self.end_headers()
                self.wfile.write(b"first")
                self.wfile.flush()
                finish.wait(3)
                self.wfile.write(b"last")

            def log_message(self, format: str, *args: object):
                pass

        with server(StreamingBackend) as upstream:
            with patch.object(tts_proxy, "serve_proxy") as serve:
                tts_proxy.run_tts_json_proxy(cfg.AUDIOCPP_SERVICE, upstream, transform=audiocpp_proxy._transform)
            with server(serve.call_args.args[0]) as proxy:
                body = json.dumps({"input": "Hello", "stream": True}).encode()
                try:
                    with urllib.request.urlopen(
                        urllib.request.Request(proxy + "/v1/audio/speech", data=body), timeout=2
                    ) as response:
                        self.assertEqual(response.read1(5), b"first")
                        self.assertFalse(finish.is_set())
                        finish.set()
                        self.assertEqual(response.read(), b"last")
                finally:
                    finish.set()

    def test_streaming_transform_sets_native_response_format(self):
        with patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True):
            result = audiocpp_proxy._transform({"input": "Hello"})
        self.assertIsNotNone(result)
        assert result is not None
        payload = result
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["response_format"], "pcm")
        options = payload["options"]
        assert isinstance(options, dict)
        self.assertEqual(options["text_chunk_mode"], "tag_aware")

        self.assertEqual(
            "voice_ref" in payload, bool(audiocpp_catalog.resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value))
        )

    def test_vocal_event_toggle_is_independent_of_tones_and_audio_streaming(self):
        for streaming in (False, True):
            for enabled in (False, True):
                settings = replace(tts_text_processing.BREEZE_VOCAL_EVENTS, enabled=enabled)
                tones = replace(tts_text_processing.BREEZE_TONES, tags_enabled=False, default_instruction="")
                with (
                    self.subTest(streaming=streaming, enabled=enabled),
                    patch.object(tts_text_processing, "BREEZE_VOCAL_EVENTS", settings),
                    patch.object(tts_text_processing, "BREEZE_TONES", tones),
                ):
                    result = audiocpp_proxy._transform(
                        {"input": "(giggle softly) Hello. (waves hello)", "stream": streaming}
                    )
                    assert result is not None
                    expected = "(giggle) Hello. waves hello" if enabled else "(giggle softly) Hello. (waves hello)"
                    self.assertEqual(result["input"], expected)

    def test_vocal_parenthetical_modes_preserve_known_events(self):
        for mode, expected in (
            (tts_text_processing.BreezeParenMode.KEEP, "(laugh) (giggle) (waves hello)"),
            (tts_text_processing.BreezeParenMode.UNWRAP, "(laugh) (giggle) waves hello"),
            (tts_text_processing.BreezeParenMode.STRIP, "(laugh) (giggle) "),
        ):
            settings = replace(tts_text_processing.BREEZE_VOCAL_EVENTS, parentheticals=mode)
            with patch.object(tts_text_processing, "BREEZE_VOCAL_EVENTS", settings):
                self.assertEqual(
                    tts_text_processing.filter_breeze_vocal_events("(laugh) (giggles) (waves hello)"), expected
                )
        settings = replace(
            tts_text_processing.BREEZE_VOCAL_EVENTS, parentheticals=tts_text_processing.BreezeParenMode.STRIP
        )
        with patch.object(tts_text_processing, "BREEZE_VOCAL_EVENTS", settings):
            self.assertIsNone(
                tts_text_processing.clean_text({"input": "(waves hello)", "model": cfg.AudiocppModel.BREEZE_TTS.value})[
                    0
                ]
            )

    def test_other_models_do_not_receive_breeze_text_rules(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                result = audiocpp_proxy._transform(
                    {
                        "input": '[Tone: happy] "Hello." (giggle softly)',
                        "model": cfg.AudiocppModel.FISH_DRAMA3_Q2.value,
                        "stream": streaming,
                        "_tone_tag": "sad",
                    }
                )
                assert result is not None
                payload = result
                self.assertEqual(payload["input"], '[Tone: happy] "Hello." (giggle softly)')
                self.assertNotIn("_tone_tag", payload)
                options = payload.get("options", {})
                assert isinstance(options, dict)
                self.assertNotIn("instruction", options)

    def test_streaming_tones_extract_inherit_and_preserve_explicit_options(self):
        with patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True):
            for text, options, expected in (
                ("[Tone: cheerful] Hello!", {}, "cheerful"),
                ("Still happy.", {}, "cheerful"),
                ("[Tone: sad] Goodbye.", {"instruction": "whisper", "guidance_scale": 2}, "whisper"),
                ("Quiet now.", {}, "whisper"),
            ):
                result = audiocpp_proxy._transform({"input": text, "options": options})
                assert result is not None
                payload = result
                spoken = payload["input"]
                request_options = payload["options"]
                assert isinstance(spoken, str) and isinstance(request_options, dict)
                self.assertNotIn("[Tone:", spoken)
                self.assertEqual(request_options["instruction"], expected)

                if "guidance_scale" in options:
                    self.assertEqual(request_options["guidance_scale"], 2)

    def test_tone_switch_combinations_use_last_before_default(self):
        for tags in (True, False):
            for default in (True, False):
                settings = replace(
                    tts_text_processing.BREEZE_TONES, tags_enabled=tags, default_instruction="calm" if default else ""
                )
                with (
                    self.subTest(tags=tags, default=default),
                    patch.object(tts_text_processing, "BREEZE_TONES", settings),
                    patch.object(tts_text_processing, "tone_state", tts_text_processing.ToneState()),
                ):
                    fallback = "calm" if default else ""
                    for text, expected in (
                        ("Hello.", fallback),
                        ("[Tone: happy] Hi!", "happy" if tags else fallback),
                        ("Again.", "happy" if tags else fallback),
                    ):
                        payload: dict[str, object] = {"input": text}
                        tts_text_processing.apply_breeze_tone(payload)
                        options = payload["options"]
                        spoken = payload["input"]
                        assert isinstance(options, dict) and isinstance(spoken, str)
                        self.assertEqual(options["instruction"], expected)
                        self.assertNotIn("[Tone:", spoken)
                    payload = {
                        "input": "Hello.",
                        "_tone_tag": "sad",
                        "options": {"instruction": "whisper", "guidance_scale": 3},
                    }
                    tts_text_processing.apply_breeze_tone(payload)
                    self.assertEqual(payload["options"], {"instruction": "whisper", "guidance_scale": 3})
                    self.assertNotIn("_tone_tag", payload)

    def test_forwarded_tone_is_ignored_when_tags_disabled(self):
        settings = replace(tts_text_processing.BREEZE_TONES, tags_enabled=False, default_instruction="calm")
        with patch.object(tts_text_processing, "BREEZE_TONES", settings):
            tts_text_processing.tone_state.last = "old tone"
            payload: dict[str, object] = {"input": "Hello.", "_tone_tag": "happy"}
            tts_text_processing.apply_breeze_tone(payload)
            options = payload["options"]
            assert isinstance(options, dict)
            self.assertEqual(options["instruction"], "calm")
            self.assertIsNone(tts_text_processing.tone_state.last)

    def test_streaming_launch_reads_native_config_without_generating_a_copy(self):
        source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
        original = json.dumps(audio_cfg.read(source)).encode("utf-8")
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(project_cfg, "GENERATED_DIR", Path(folder)),
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True),
            patch.object(audiocpp, "launch_process") as launch,
            patch.object(audiocpp, "print_ready"),
        ):
            audiocpp.launch(report_vram=False)
            command = launch.call_args.args[0]
            runtime_path = Path(command[command.index("--config") + 1])
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            expected = json.loads(original)
            self.assertEqual(runtime, expected)
            self.assertEqual(runtime_path, Path(folder) / "shared" / "configs" / source.name)
            self.assertNotIn("{AI_ROOT}", runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(audio_cfg.read(source), json.loads(original))

    def test_streaming_defaults_preserve_explicit_request_options(self):
        settings = replace(cfg.AUDIOCPP_SERVICE.streaming, stream_frames_per_event=16, stream_lookahead_margin=12)
        with (
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming", settings),
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True),
        ):
            result = audiocpp_proxy._transform({"input": "Hello", "options": {"stream_frames_per_event": 8}})
        assert result is not None
        options = result["options"]
        assert isinstance(options, dict)
        self.assertEqual(options["stream_frames_per_event"], 8)
        self.assertEqual(options["stream_lookahead_margin"], 12)

    def test_explicit_buffered_request_overrides_streaming_default(self):
        with (
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True),
            patch.object(tts_text_processing, "clean_text", return_value=("Hello", 0.0)),
        ):
            result = audiocpp_proxy._transform({"input": "Hello", "stream": False, "response_format": "wav"})
        assert result is not None
        payload = result
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["response_format"], "wav")
        self.assertNotIn("stream_format", payload)


class _Tee:
    """Mirror runner output to the console and the regression log."""

    def __init__(self, *streams) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str):
        # - pytest reads stream attributes such as encoding and errors
        return getattr(self._streams[0], name)


def _run_native_suite(suite: str, live_target: str | None, probe_names: list[str]) -> int:
    names: list[str] = list(live_frameworks.LAUNCHER_TARGETS) if live_target in (None, "all") else [live_target]
    title = {"launchers": "Live Launchers", "backends": "Live Backends", "all": "Live All"}[suite]
    previous_title = os.environ.get("AI_TEST_TITLE")
    os.environ["AI_TEST_TITLE"] = title
    launch_util.set_console_title(title)
    try:
        if suite == "backends":
            return 0 if quick_validation.run_probes(probe_names) else 1
        if suite == "launchers":
            return 0 if live_frameworks.run_live(names) else 1
        launchers_ok = live_frameworks.run_live(names)
        backends_ok = quick_validation.run_probes(probe_names)
        return 0 if launchers_ok and backends_ok else 1
    except RuntimeError as error:
        print(f"[REFUSE] {error}", file=sys.stderr)
        return 2
    finally:
        launch_util.set_console_title(title)
        if previous_title is None:
            os.environ.pop("AI_TEST_TITLE", None)
        else:
            os.environ["AI_TEST_TITLE"] = previous_title


DEFAULT_GROUPS: tuple[type[unittest.TestCase], ...] = (
    DefaultPaths,
    DefaultPorts,
    LaunchCommands,
    StateAndReadiness,
    ProxyHTTP,
    LauncherBehaviors,
)


def main(extra_groups: tuple[type[unittest.TestCase], ...] = ()) -> int:

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("launchers", "backends", "all"),
        help="native suite to run: launcher wiring, backend probes, or both",
    )
    parser.add_argument(
        "--live",
        choices=(*live_frameworks.LAUNCHER_TARGETS, "all"),
        help="launcher target for --suite launchers/all (default: all)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=tuple(quick_validation.PROBES),
        default=list(quick_validation.PROBES),
        help="probe target for --suite backends/all (default: all)",
    )
    parser.add_argument("--timeout", type=float, default=300, help="live startup/generation timeout in seconds")
    parser.add_argument(
        "--with-regressions", action="store_true", help="run the model-free suite before the native suite"
    )
    parser.add_argument("--ini-set", action="append", default=[], help=argparse.SUPPRESS)
    parser.add_argument(
        "--worker", choices=("sdcpp", "audiocpp", "llamacpp", "kobold", "dsh", "dsh-headless"), help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    live_frameworks.live_timeout = args.timeout
    if args.worker:
        return live_frameworks.worker_main(args.worker, args.ini_set)
    native_suite = args.suite or ("launchers" if args.live else None)
    if native_suite and not args.with_regressions:
        return _run_native_suite(native_suite, args.live, args.only)
    groups = (*DEFAULT_GROUPS, *extra_groups)
    # - guard the tests themselves against accidental process/port side effects
    output = CasePaths(__file__).new_run()
    report = RunReport(
        "default regressions",
        "model-free",
        settings={
            "test_mode": "model_free",
            "scope": ["mocked_unit", "loopback_integration", "local_assets"],
            "native_suite_after_regressions": native_suite,
        },
    )
    report.save(output)
    log_path = output.logs / f"regression_{time.time_ns()}.log"
    return _run_regressions(groups, output, report, log_path, native_suite, args.live, args.only)


class _PytestRun:
    """Collect per-test durations and outcomes the report files already record."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self.outcomes: list[tuple[str, str, str]] = []

    def pytest_runtest_logreport(self, report) -> None:
        self.seconds[report.nodeid] = self.seconds.get(report.nodeid, 0.0) + report.duration
        if report.skipped:
            self.outcomes.append(("skipped", report.nodeid, str(report.longrepr)))
        elif report.failed:
            status = "failure" if report.when == "call" else "error"
            self.outcomes.append((status, report.nodeid, report.longreprtext))
        elif report.when == "call" and report.passed:
            self.outcomes.append(("passed", report.nodeid, ""))


def _pytest_nodeids(groups: tuple[type[unittest.TestCase], ...]) -> list[str]:
    """Explicit class selection: unregistered modules must never be collected."""
    nodeids = []
    for group in groups:
        module = sys.modules[group.__module__]
        source = Path(str(module.__file__)).as_posix()
        nodeids.append(f"{source}::{group.__qualname__}")
    return nodeids


def _run_regressions(
    groups: tuple[type[unittest.TestCase], ...],
    output: RunPaths,
    report: RunReport,
    log_path: Path,
    native_suite: str | None,
    live: str | None,
    only: list[str],
) -> int:
    """Run the registered classes through pytest, inside the model-free process guards."""
    import pytest

    from scripts.tests.shared.model_free import model_free_boundary

    runner = _PytestRun()
    console_out, console_err = sys.stdout, sys.stderr
    with log_path.open("w", encoding="utf-8") as log:
        tee_out, tee_err = _Tee(console_out, log), _Tee(console_err, log)
        with (
            model_free_boundary(),
            contextlib.redirect_stdout(tee_out),
            contextlib.redirect_stderr(tee_err),
            patch.object(launch_util, "kill_processes_on_ports", side_effect=AssertionError("unmocked port kill")),
            patch.object(
                launch_util, "assign_process_to_job", side_effect=AssertionError("unmocked process assignment")
            ),
        ):
            code = pytest.main(
                ["-q", "-s", "-rs", "--no-header", "--tb=short", "-p", "no:cacheprovider", *_pytest_nodeids(groups)],
                plugins=[runner],
            )
    (output.artifacts / "timings.json").write_text(json.dumps(runner.seconds, indent=2), encoding="utf-8")
    summary_lines: list[str] = []
    for status, test_id, detail in runner.outcomes:
        if status == "passed":
            continue
        summary_lines.append(f"{status.upper()}: {test_id}\n{detail}\n")
        report.results.append(
            {"test": test_id, "status": status, "message": detail.strip().splitlines()[-1] if detail.strip() else ""}
        )
    (output.artifacts / "unittest.txt").write_text("\n".join(summary_lines), encoding="utf-8")
    report.status = "completed" if code == 0 else "failed"
    if code:
        report.error = f"{sum(1 for status, _, _ in runner.outcomes if status == 'failure')} failures, "
        report.error += f"{sum(1 for status, _, _ in runner.outcomes if status == 'error')} errors"
    report.save(output)
    print(f"[LOG] regression details: {log_path}")
    print(f"[LOG] failure details: {output.artifacts / 'unittest.txt'}")
    if code:
        return 1
    if native_suite:
        return _run_native_suite(native_suite, live, only)
    print("[WARN] Model inference not tested. Use bat/tests/test_live_launchers.bat or test_live_backends.bat.")
    return 0
    print("[WARN] Model inference not tested. Use bat/tests/test_live_launchers.bat or test_live_backends.bat.")
    return 0


if __name__ == "__main__":
    with timed("shared/frameworks_smoke"):
        raise SystemExit(main())
