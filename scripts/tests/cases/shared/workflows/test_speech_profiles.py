"""Speech engine routing and CPU profile contracts without native model launches."""

import json
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import practice_models
from scripts.launchers.koboldcpp import kobold, kobold_lite, speech
from scripts.tests.shared.paths import CasePaths


class SpeechProfiles(unittest.TestCase):
    def test_speech_engines_are_the_configured_one_and_the_audiocpp_proxy(self):
        self.assertEqual([engine.value for engine in cfg.KoboldcppSpeechStartupEngine], ["configured", "audiocpp"])

    def test_practice_default_is_supertonic_with_a_preset_voice(self):
        spec = practice_models.tts_spec()
        self.assertEqual(spec["family"], "supertonic")
        self.assertEqual(spec["id"], cfg.SUPERTONIC_MODEL)
        self.assertEqual(cfg.LANGUAGE_PRACTICE.tts_voice, cfg.SUPERTONIC_TTS.voice)
        self.assertEqual(cfg.tts_class_for(cfg.SUPERTONIC_MODEL).value, "fast-multilingual")

    def test_practice_languages_are_listed_first(self):
        rows = practice_models.language_profiles()
        self.assertEqual([row["code"] for row in rows[:5]], list(cfg.PRACTICE_LANGUAGES))
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[5]["code"], "ko")  # the model's own order takes over after the targets

    def test_existing_session_is_not_replaced(self):
        with (
            patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", cfg.KoboldcppSpeechStartupEngine.CONFIGURED),
            patch.object(kobold, "backend_running", return_value=True),
            patch.object(kobold, "start_kobold") as start,
            self.assertRaisesRegex(RuntimeError, "occupied"),
        ):
            kobold.main(["--speech-engine", "audiocpp"])
        start.assert_not_called()

    def test_kobold_loads_no_tts_model_itself(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", cfg.KoboldcppSpeechStartupEngine.AUDIOCPP):
            command = kobold.server_command("shared")
        self.assertNotIn("--ttsmodel", command)
        self.assertNotIn("--ttsgpu", command)

    def test_external_config_selects_cpu_without_other_models(self):
        spec = practice_models.tts_spec()
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(project_cfg, "GENERATED_DIR", Path(folder)),
        ):
            command = speech.audio_command(18881)
            config = json.loads(Path(command[command.index("--config") + 1]).read_text())
        self.assertEqual(config["backend"], "cpu")
        self.assertEqual(config["threads"], cfg.AUDIOCPP_SPEECH.threads)
        self.assertEqual([model["id"] for model in config["models"]], [spec["id"]])
        self.assertEqual(config["models"][0]["path"], spec["path"])
        self.assertEqual(command[-2:], ["--model", spec["id"]])

    def test_speech_provider_routes_to_the_audiocpp_proxy(self):
        def serve(handler, *_args):
            instance = handler.__new__(handler)
            instance.path = "/v1/audio/speech"
            instance.headers = Message()
            instance._forward("POST")

        payload = json.dumps(
            {"input": "Hello", "model": "stale-model", "voice_ref": "stale.wav", "stream": True}
        ).encode()
        with (
            patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", cfg.KoboldcppSpeechStartupEngine.AUDIOCPP),
            patch.object(kobold_lite, "serve_proxy", side_effect=serve),
            patch.object(kobold_lite, "read_request_body", return_value=payload),
            patch.object(kobold_lite, "relay_stream") as relay,
        ):
            kobold_lite.run_proxy()
            target = relay.call_args.args[2]
            body = json.loads(relay.call_args.args[4])
        self.assertEqual(target, f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}/v1/audio/speech")
        self.assertEqual(body["model"], cfg.SUPERTONIC_MODEL)
        self.assertNotIn("voice_ref", body)
        self.assertEqual(body["options"]["voice_id"], cfg.SUPERTONIC_TTS.voice)
        self.assertNotIn("voice", body)
        self.assertTrue(body["stream"])

    def test_the_chat_default_is_a_model_the_tracked_catalog_can_resolve(self):
        from scripts.config.models import catalog

        tracked = {model.label for model in catalog.load_catalog(overlay=False)}
        self.assertEqual(cfg.KOBOLDCPP_CHAT_LABELS[0], cfg.DEFAULT_CHAT_MODEL)
        self.assertIn(cfg.DEFAULT_CHAT_MODEL, tracked)
        self.assertIn(cfg.KOBOLD_CHAT.llm_model, cfg.KOBOLDCPP_MODELS)

    def test_selection_separates_tested_models_from_selectable_untested_ones(self):
        rows = practice_models.tts_models()
        tested = {row["id"] for row in rows if row["coverage"] == "tested"}
        untested = {row["id"] for row in rows if row["coverage"] == "untested"}
        self.assertEqual(tested, set(cfg.LIVE_TESTED_TTS_MODELS))
        self.assertEqual(untested, {cfg.KOKORO_MODEL})
        self.assertEqual(tested | untested, {row["id"] for row in rows})

    def test_live_coverage_names_the_three_arms_that_speak_with_a_model(self):
        from scripts.config import models
        from scripts.tests.cases.audiocpp import audiocpp_backend_compare

        spoke_with = {
            models.path(cfg.AUDIOCPP_SERVICE.model),
            models.path(cfg.LANGUAGE_PRACTICE.tts_model),
            audiocpp_backend_compare.PROFILES["ming3-tts"].model,
        }
        self.assertEqual(spoke_with, {models.path(label) for label in cfg.LIVE_TESTED_TTS_MODELS})

    def test_invalid_speech_json_is_rejected_before_relay(self):
        with self.assertRaises(ValueError):
            speech.speech_body(b"[]")


if __name__ == "__main__":
    unittest.main()
