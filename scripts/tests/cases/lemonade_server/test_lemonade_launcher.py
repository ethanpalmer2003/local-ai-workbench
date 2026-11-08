"""Lemonade Server startup configuration; no process is started and no model is loaded."""

import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.lemonade_server import lemonade
from scripts.tests.shared.paths import CasePaths


class LemonadeOwnedStartTests(unittest.TestCase):
    def test_an_owned_start_joins_the_launch_job_and_a_plain_start_does_not(self):
        from unittest.mock import MagicMock, patch

        from scripts.launchers.lemonade_server import lemonade

        process = MagicMock(pid=99)
        with (
            patch.object(lemonade.launch_util, "launch_process", return_value=process) as launched,
            patch.object(lemonade, "ready", return_value=True),
            patch.object(lemonade, "new_log_path", return_value=MagicMock()),
        ):
            lemonade.start(MagicMock(), 1234, owned=True)
            self.assertTrue(launched.call_args.kwargs["bind_job"])
            lemonade.start(MagicMock(), 1234)
            self.assertFalse(launched.call_args.kwargs["bind_job"])


class LemonadeLauncherTests(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.paths = CasePaths(__file__).new_run()
        self.config = self.paths.temp / "config.json"
        self.original = json.dumps(
            {"extra_models_dir": "", "log_level": "info", "port": 13305, "websocket_port": 9000}, indent=2
        )
        self.config.write_text(self.original, encoding="utf-8")

    def service(self):
        return patch.object(cfg, "LEMONADE_SERVICE", replace(cfg.LEMONADE_SERVICE, config=self.config))

    def settings(self) -> dict[str, object]:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_run_config_points_the_server_at_our_weights_then_restores(self):
        output = self.paths.temp / "gguf"
        with self.service(), lemonade.run_config(output, port=14001):
            settings = self.settings()
            self.assertEqual(settings["extra_models_dir"], str(output))
            self.assertEqual(settings["port"], 14001)
            self.assertEqual(settings["websocket_port"], "auto")
            self.assertEqual(settings["log_level"], "info")
        self.assertEqual(self.config.read_text(encoding="utf-8"), self.original)

    def test_run_config_restores_after_a_failed_run(self):
        with (
            self.service(),
            self.assertRaisesRegex(RuntimeError, "comparison failed"),
            lemonade.run_config(self.paths.temp / "gguf"),
        ):
            raise RuntimeError("comparison failed")
        self.assertEqual(self.config.read_text(encoding="utf-8"), self.original)

    def test_command_and_health_route_come_from_the_service_settings(self):
        with self.service():
            self.assertEqual(
                lemonade.server_command(), [str(cfg.LEMONADE_SERVICE.exe), "--port", str(cfg.LEMONADE_SERVICE.port)]
            )
            self.assertEqual(lemonade.health_url(), f"http://127.0.0.1:{cfg.LEMONADE_SERVICE.port}/api/v0/health")
            self.assertEqual(lemonade.server_command(14002)[-1], "14002")

    def test_ready_needs_a_listening_port_and_an_answering_route(self):
        with patch.object(lemonade.launch_util, "port_listening", return_value=False):
            self.assertFalse(lemonade.ready(timeout_s=0.01))
        with (
            patch.object(lemonade.launch_util, "port_listening", return_value=True),
            patch.object(lemonade, "_answers", return_value=False) as answers,
        ):
            self.assertFalse(lemonade.ready(timeout_s=0.2))
        self.assertGreater(answers.call_count, 0)
        with (
            patch.object(lemonade.launch_util, "port_listening", return_value=True),
            patch.object(lemonade, "_answers", return_value=True),
        ):
            self.assertTrue(lemonade.ready(timeout_s=1))


if __name__ == "__main__":
    unittest.main()
