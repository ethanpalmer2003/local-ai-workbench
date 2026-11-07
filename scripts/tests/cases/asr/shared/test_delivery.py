"""Delivery negotiation and overrides without devices, native processes or network."""

import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.config.shared import speech_delivery
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import delivery, live, practice_models
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.paths import CasePaths


class DeliveryTests(unittest.TestCase):
    def test_preference_chain_and_model_override_persistence(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(speech_delivery, "state_path", return_value=Path(folder) / "delivery.json"),
        ):
            self.assertEqual(
                speech_delivery.resolve("tts", "one", ["streaming", "chunked", "whole"])["mode"], "streaming"
            )
            speech_delivery.save("tts", "one", "whole")
            self.assertEqual(speech_delivery.resolve("tts", "one", ["streaming", "whole"])["mode"], "whole")
            self.assertEqual(speech_delivery.resolve("tts", "two", ["streaming", "whole"])["mode"], "streaming")
            speech_delivery.save("tts", "one", "auto")
            self.assertEqual(speech_delivery.overrides(), {})
            speech_delivery.save("llm", "chat", "chunked")
            self.assertEqual(speech_delivery.resolve("llm", "chat", ["streaming", "whole"])["mode"], "whole")
            with self.assertRaises(ValueError):
                speech_delivery.save("tts", "one", "unsupported-mode")

    def test_asr_does_not_confuse_vad_segments_with_streaming(self):
        with patch.object(speech_delivery, "overrides", return_value={}):
            self.assertEqual(delivery.asr_plan(cfg.AsrStartupEngine.AUDIOCPP)["mode"], "streaming")
            self.assertEqual(delivery.asr_plan(cfg.AsrStartupEngine.WHISPER_VULKAN)["mode"], "chunked")
            self.assertEqual(delivery.asr_plan(cfg.AsrStartupEngine.QWEN3_ASR)["mode"], "whole")
        with patch.object(speech_delivery, "overrides", return_value={"asr:audiocpp-nemotron": "whole"}):
            self.assertFalse(live.supported(cfg.AsrStartupEngine.AUDIOCPP))

    def test_tts_capability_and_request_format_are_preserved(self):
        spec = {"id": cfg.LANGUAGE_PRACTICE.tts_model, "family": "kokoro_tts", "path": "unused", "mode": "streaming"}
        with (
            patch.object(speech_delivery, "overrides", return_value={}),
            patch.object(practice_models, "tts_spec", return_value=spec),
        ):
            self.assertEqual(delivery.tts_plan()["mode"], "streaming")
            payload = practice_models.speech_body(
                {"input": "Bonjour", "voice": "ff_siwis", "options": {"language": "fr-fr"}}
            )
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["response_format"], "pcm")
        options = payload["options"]
        assert isinstance(options, dict)
        self.assertEqual(options["language"], "fr-fr")
        with (
            patch.object(speech_delivery, "overrides", return_value={}),
            patch.object(practice_models, "tts_spec", return_value={**spec, "mode": "buffered"}),
        ):
            self.assertEqual(delivery.tts_plan()["mode"], "chunked")
            with self.assertRaisesRegex(ValueError, "Streaming is not supported"):
                practice_models.speech_body({"input": "Bonjour", "stream": True})

    def test_override_route_rejects_arbitrary_model_ids(self):
        handler = SimpleNamespace()
        controls = Mock()
        controls.catalog.return_value = {"tts": [{"id": "registered"}]}
        with (
            patch(
                "scripts.launchers.proxy_util.read_request_body",
                return_value=b'{"stage":"tts","model":"arbitrary","mode":"whole"}',
            ),
            patch("scripts.launchers.proxy_util.send_json_error") as error,
            patch.object(speech_delivery, "save") as save,
        ):
            self.assertTrue(delivery.route(handler, "POST", "/workspace/delivery", controls))
        self.assertEqual(error.call_args.args[1], 400)
        save.assert_not_called()

    @fixture_processes()
    def test_browser_delivery_negotiation(self):
        result = subprocess.run(
            [cfg.PI_CLIENT.node_cmd, str(Path(__file__).with_name("delivery.cjs"))],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
