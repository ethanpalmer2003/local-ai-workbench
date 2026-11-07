"""Strata/Pi API selection, credential handling and backend ownership without inference."""

from scripts.tests.shared.process_fixtures import running_process

import io
import json
import unittest
from contextlib import ExitStack
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts.launchers import launch_util
from scripts.launchers.strata import strata_pi
from scripts.tests.shared.paths import CasePaths


def connection(port: int = 18501) -> strata_pi.StrataConnection:
    return strata_pi.StrataConnection(Path("saved.json"), {"model_name": "swift", "args": []}, port, "test-key")


MODEL = {"id": "swift", "meta": {"n_ctx": 32768}, "architecture": {"input_modalities": ["text"]}}


class StrataPiTests(unittest.TestCase):
    def test_config_discovery_handles_redirected_local_appdata(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            source = root / "AppData" / "Local" / "Strata" / "install" / f"strata-{strata_pi.cfg.STRATA_SERVICE.model}.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps({"model_name": strata_pi.cfg.STRATA_SERVICE.model_name, "port": 8080}), encoding="utf-8"
            )
            with (
                patch.object(strata_pi.Path, "home", return_value=root),
                patch.object(strata_pi.cfg.STRATA_SERVICE, "config_path", root / "missing.json"),
                patch.dict(strata_pi.os.environ, {"LOCALAPPDATA": str(root / "sandbox-local")}),
            ):
                saved = strata_pi.saved_connections()
            self.assertEqual([entry.config_path for entry in saved], [source])

    def test_project_config_is_used_before_desktop_discovery(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "server.json"
            path.write_text(json.dumps({"model_name": "swift", "port": 18501}), encoding="utf-8")
            with patch.object(strata_pi.cfg.STRATA_SERVICE, "config_path", path):
                saved = strata_pi.saved_connections()
            self.assertEqual([entry.config_path for entry in saved], [path])

    def test_model_probe_uses_auth_and_rejects_a_different_model(self):
        response = io.BytesIO(json.dumps({"data": [MODEL]}).encode())
        with patch.object(strata_pi.urllib.request, "urlopen", return_value=response) as request:
            self.assertEqual(strata_pi.ready_model(connection()), MODEL)
            self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer test-key")
        response = io.BytesIO(b'{"data": [{"id": "other"}]}')
        with (
            patch.object(strata_pi.urllib.request, "urlopen", return_value=response),
            self.assertRaisesRegex(RuntimeError, "different model"),
        ):
            strata_pi.ready_model(connection())

    def test_auth_failure_is_not_treated_as_a_stopped_server(self):
        error = HTTPError("http://127.0.0.1", 401, "Unauthorized", Message(), None)
        with (
            patch.object(strata_pi.urllib.request, "urlopen", side_effect=error),
            self.assertRaisesRegex(RuntimeError, "HTTP 401"),
        ):
            strata_pi.ready_model(connection())

    def test_pi_provider_preserves_other_providers_and_does_not_save_the_key(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            path = root / "models.json"
            path.write_text(json.dumps({"providers": {"llamacpp": {"apiKey": "noop"}}}), encoding="utf-8")
            with patch.object(strata_pi.cfg.PI_CLIENT, "agent_dir", root):
                command = strata_pi.pi_command(connection(), MODEL)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("llamacpp", data["providers"])
            self.assertEqual(data["providers"]["strata"]["apiKey"], "${STRATA_API_KEY}")
            self.assertNotIn("test-key", path.read_text(encoding="utf-8"))
            self.assertEqual(data["providers"]["strata"]["models"][0]["contextWindow"], 32768)
            self.assertEqual(command[-4:], ["--provider", "strata", "--model", "swift"])

    def test_owned_backend_reads_native_config_and_keeps_credentials_in_memory(self):
        saved = connection()
        saved.config.update({"vram_reserve_mib": 512, "args": ["--expert-cache", "auto", "--mmap-experts"]})
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            saved.config_path = root / "saved.json"
            saved.config_path.write_text(json.dumps(saved.config), encoding="utf-8")
            original = saved.config_path.read_bytes()
            with (
                patch.object(strata_pi, "LOG_DIR", root / "logs"),
                patch.dict(strata_pi.os.environ, {"STRATA_API_KEY": "test-env-key"}),
            ):
                ready = strata_pi.prepare_backend(saved)
            self.assertEqual(ready.config_path, saved.config_path)
            self.assertEqual(ready.config, saved.config)
            self.assertEqual(ready.api_key, "test-env-key")
            self.assertEqual(ready.port, strata_pi.cfg.STRATA_SERVICE.port)
            self.assertEqual(saved.config_path.read_bytes(), original)
            self.assertEqual(list((root / "logs").iterdir()), [])

    def test_engine_switches_from_the_config_reach_the_engine_process(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            saved = connection()
            saved.config["env"] = {"STRATA_HIP_WMMA": "1", "STRATA_PREFILL_RING": 96}
            saved.config_path = root / "saved.json"
            saved.config_path.write_text(json.dumps(saved.config), encoding="utf-8")
            with (
                patch.object(launch_util, "launch_process", return_value=Mock()) as launch,
                patch.object(Path, "is_file", return_value=True),
            ):
                strata_pi.start_backend(saved)
            command = launch.call_args.args[0]
            resolved = Path(command[command.index("--config") + 1])
            self.assertNotIn("{AI_ROOT}", resolved.read_text(encoding="utf-8"))
        environment = launch.call_args.kwargs["env"]
        self.assertEqual(environment["STRATA_HIP_WMMA"], "1")
        self.assertEqual(environment["STRATA_PREFILL_RING"], "96")
        self.assertEqual(environment["STRATA_API_KEY"], saved.api_key)

    def test_backend_only_launch_rejects_inherited_mcp_servers(self):
        for key in ("mcp_servers", "mcpServers"):
            saved = connection()
            saved.config[key] = {"tools": {"command": "unused"}}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "backend-only"):
                strata_pi.prepare_backend(saved)

    def run_launcher(
        self, ready: bool, startup_error: bool = False, api_key: str = "test-key"
    ) -> tuple[Mock, Mock, Mock]:
        process = running_process(pid=123)
        with ExitStack() as stack:
            root = Path(stack.enter_context(CasePaths(__file__).temporary_directory()))
            saved = connection()
            saved.api_key = api_key
            saved.config_path = root / "saved.json"
            saved.config_path.write_text("{}", encoding="utf-8")
            stack.enter_context(patch("builtins.print"))
            stack.enter_context(patch("scripts.launchers.runtime.execution_context.execution_context", return_value={}))
            stack.enter_context(patch.object(strata_pi, "saved_connections", return_value=[saved]))
            stack.enter_context(patch.object(strata_pi, "ready_model", return_value=MODEL if ready else None))
            stack.enter_context(patch.object(launch_util, "backend_running", return_value=False))
            start = stack.enter_context(patch.object(strata_pi, "start_backend", return_value=process))
            stop = stack.enter_context(patch.object(launch_util, "kill_process_tree"))
            stack.enter_context(patch.object(strata_pi, "prepare_backend", return_value=connection()))
            wait = stack.enter_context(patch.object(strata_pi, "wait_for_model", return_value=MODEL))
            if startup_error:
                wait.side_effect = TimeoutError("startup failed")
            stack.enter_context(patch.object(strata_pi, "prepare_pi_env", return_value={}))
            stack.enter_context(patch.object(strata_pi, "pi_command", return_value=["pi"]))
            client = stack.enter_context(patch.object(strata_pi.subprocess, "run"))
            if startup_error:
                with self.assertRaisesRegex(TimeoutError, "startup failed"):
                    strata_pi.main([])
            else:
                strata_pi.main(["--", "--continue"])
        return start, stop, client

    def test_reused_backend_is_never_started_or_stopped(self):
        start, stop, client = self.run_launcher(ready=True)
        start.assert_not_called()
        stop.assert_not_called()
        self.assertEqual(client.call_args.args[0], ["pi", "--continue"])
        self.assertEqual(client.call_args.kwargs["env"]["STRATA_API_KEY"], "test-key")

    def test_owned_backend_stops_on_exit_and_on_failed_startup(self):
        for startup_error in (False, True):
            with self.subTest(startup_error=startup_error):
                start, stop, client = self.run_launcher(ready=False, startup_error=startup_error)
                start.assert_called_once()
                stop.assert_called_once_with(123, ports=18501)
                self.assertEqual(client.call_count, 0 if startup_error else 1)

    def test_unauthenticated_local_backend_still_has_a_usable_pi_provider(self):
        _, _, client = self.run_launcher(ready=True, api_key="")
        self.assertEqual(client.call_args.kwargs["env"]["STRATA_API_KEY"], "noop")


if __name__ == "__main__":
    unittest.main()
