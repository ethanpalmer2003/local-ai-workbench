"""Native UI routing and injection; no model startup or network access."""

import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import speech_ui
from scripts.tests.shared.paths import CasePaths


class SpeechUiTests(unittest.TestCase):
    def test_native_ui_injects_shared_client_and_loads_only_chat(self):
        handler = SimpleNamespace(path="/?ui=llama", headers={})
        runtime = Mock()
        runtime.chat_url.return_value = "http://127.0.0.1:5004"
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "index.html").write_text("<html><head></head><body>native</body></html>")
            with (
                patch.object(speech_ui.project_cfg, "LLAMACPP_SPEECH_UI_DIR", root),
                patch.object(speech_ui, "send_bytes") as send,
            ):
                self.assertTrue(speech_ui.route(handler, "GET", runtime))
        runtime.load.assert_called_once_with("llm")
        html = send.call_args.args[2].decode()
        self.assertIn("/launchers/shared/browser/speech_client.js", html)
        self.assertIn("/llama-speech.js", html)
        self.assertIn("<body>native", html)

    def test_practice_route_and_non_get_requests_are_untouched(self):
        runtime = Mock()
        self.assertFalse(speech_ui.route(SimpleNamespace(path="/practice", headers={}), "GET", runtime))
        self.assertFalse(speech_ui.route(SimpleNamespace(path="/?ui=llama", headers={}), "POST", runtime))
        runtime.load.assert_not_called()

    def test_native_pwa_cannot_take_over_shared_origin(self):
        with patch.object(speech_ui, "send_bytes") as send:
            self.assertTrue(
                speech_ui.route(SimpleNamespace(path="/sw.js", headers={"Service-Worker": "script"}), "GET", Mock())
            )
        self.assertEqual(send.call_args.args[1], 404)

    def test_built_assets_are_served_without_loading_models(self):
        runtime = Mock()
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "_app").mkdir()
            (root / "_app/controls.js").write_text("window.nativeControls = true;")
            with (
                patch.object(speech_ui.project_cfg, "LLAMACPP_SPEECH_UI_DIR", root),
                patch.object(speech_ui, "send_bytes") as send,
            ):
                self.assertTrue(speech_ui.route(SimpleNamespace(path="/_app/controls.js", headers={}), "GET", runtime))
                self.assertFalse(speech_ui.route(SimpleNamespace(path="/../index.html", headers={}), "GET", runtime))
        self.assertIn(b"nativeControls", send.call_args.args[2])
        runtime.load.assert_not_called()

    def test_missing_build_fails_before_model_start(self):
        runtime = Mock()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(speech_ui.project_cfg, "LLAMACPP_SPEECH_UI_DIR", Path(folder)),
            self.assertRaisesRegex(RuntimeError, "Build the native speech UI"),
        ):
            speech_ui.route(SimpleNamespace(path="/?ui=llama", headers={}), "GET", runtime)
        runtime.load.assert_not_called()

    def test_shared_browser_speech_transport(self):
        result = subprocess.run(
            [cfg.PI_CLIENT.node_cmd, str(Path(__file__).with_name("speech_ui.cjs"))],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
