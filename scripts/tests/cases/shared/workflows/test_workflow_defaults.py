"""The two workflows declare their default speech stack once; every consumer reads from it."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from scripts.config import models
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import practice_models
from scripts.launchers.llamacpp import chat_models


class WorkflowDefaultsTests(unittest.TestCase):
    def test_chat_profile_owns_the_kobold_and_breeze_defaults(self):
        # - the overlay may replace the model, voice and instruction; the wiring must not change
        self.assertEqual(cfg.KOBOLD_CHAT.framework, "koboldcpp")
        self.assertIsNone(cfg.KOBOLD_CHAT.asr_engine)
        self.assertEqual(cfg.KOBOLD_CHAT.clone_voice, bool(cfg.KOBOLD_CHAT.tts_voice))
        self.assertTrue(cfg.KOBOLD_CHAT.llm_model.startswith("koboldcpp/"))
        self.assertEqual(cfg.KOBOLD_CHAT.tts_model, cfg.AUDIOCPP_SERVICE.model)
        self.assertIn(cfg.KOBOLD_CHAT.tts_model, cfg.BREEZE_MODELS)
        self.assertEqual(cfg.KOBOLDCPP_SERVICE.model, cfg.KOBOLD_CHAT.llm_model)
        self.assertEqual(cfg.KOBOLDCPP_SERVICE.transcription_engine, cfg.AsrStartupEngine.EMBEDDED)
        self.assertEqual(cfg.AUDIOCPP_SERVICE.voice, cfg.KOBOLD_CHAT.tts_voice)
        self.assertEqual(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value, cfg.KOBOLD_CHAT.tts_voice)

    def test_language_practice_profile_owns_the_gemma_kokoro_and_asr_defaults(self):
        self.assertEqual(cfg.LANGUAGE_PRACTICE.framework, "llamacpp")
        self.assertFalse(cfg.LANGUAGE_PRACTICE.clone_voice)
        self.assertEqual(cfg.ASR_SERVICE.engine, cfg.LANGUAGE_PRACTICE.asr_engine)
        self.assertEqual(chat_models.default_id(), cfg.LANGUAGE_PRACTICE.llm_model)
        with patch.object(practice_models, "active_tts_id", None):
            self.assertEqual(practice_models.tts_id(), cfg.LANGUAGE_PRACTICE.tts_model)
        self.assertEqual(cfg.KOKORO_TTS.voice, cfg.LANGUAGE_PRACTICE.tts_voice)
        self.assertEqual(cfg.LANGUAGE_PRACTICE.tts_model, cfg.KOKORO_TTS_PACKAGES[cfg.DEFAULT_KOKORO_PACKAGE])
        self.assertEqual(cfg.GEMMA_AUDIO_ASR.model, models.path(cfg.LANGUAGE_PRACTICE.llm_model))
        self.assertEqual(cfg.KOKORO_TTS.audiocpp_model, models.path(cfg.LANGUAGE_PRACTICE.tts_model))

    def test_derived_defaults_read_the_profile_rather_than_each_other(self):
        with patch.object(cfg, "LANGUAGE_PRACTICE", replace(cfg.LANGUAGE_PRACTICE, llm_model="elsewhere/chat")):
            self.assertEqual(chat_models.default_id(), "elsewhere/chat")
        with patch.object(cfg, "LANGUAGE_PRACTICE", replace(cfg.LANGUAGE_PRACTICE, tts_model="elsewhere/tts")), patch.object(
            practice_models, "active_tts_id", None
        ):
            self.assertEqual(practice_models.tts_id(), "elsewhere/tts")


if __name__ == "__main__":
    unittest.main()
