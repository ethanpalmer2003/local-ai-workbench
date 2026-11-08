"""Shared character/practice speech cleanup: emoji sequences, multilingual text and adapter parity."""

import json
import unittest

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import tts_text_processing
from scripts.launchers.koboldcpp import kokoro
from scripts.launchers.shared.media import text_processing


class TextProcessingTests(unittest.TestCase):
    def test_english_speech_keeps_romanization_without_changing_display_text(self):
        original = "日本語も話せますよ！ (Nihongo mo hanasemasu yo!)"
        payload: dict[str, object] = {"input": original, "options": {"language": "en-us"}}
        text_processing.clean_speech_payload(payload)
        cleaned = payload["input"]
        assert isinstance(cleaned, str)
        self.assertNotIn("日本語", cleaned)
        self.assertIn("(Nihongo mo hanasemasu yo!)", cleaned)
        self.assertIn("日本語", original)
        self.assertEqual(text_processing.clean_text(original, language="ja"), original)

    def test_voice_script_filter_preserves_accents_and_selected_scripts(self):
        self.assertEqual(
            text_processing.clean_text("café français español 日本語", language="fr-fr"), "café français español"
        )
        self.assertEqual(text_processing.clean_text("हिन्दी English", language="hi"), "हिन्दी English")
        self.assertEqual(text_processing.clean_text("你好 English", language="zh"), "你好 English")
        with self.assertRaises(ValueError):
            text_processing.clean_speech_payload({"input": "日本語"}, language="en-us")

    def test_emoji_sequences_and_bmp_symbols_are_removed(self):
        cases = ["🙂", "❤️", "👨‍👩‍👧‍👦", "👩🏽‍💻", "🇨🇦", "1️⃣", "☀️", "✅", "🏴\U000e0067\U000e0062\U000e007f"]
        for emoji in cases:
            with self.subTest(emoji=ascii(emoji)):
                self.assertEqual(text_processing.clean_text("Hello" + emoji + "world"), "Hello world")
                self.assertEqual(text_processing.clean_text(emoji), "")

    def test_languages_numbers_and_nonemoji_symbols_survive(self):
        text = "Français español 中文 日本語 한국어 العربية हिन्दी 𠀀 𐐀 123 * 2 + 3 = 5 €"
        self.assertEqual(text_processing.clean_text(text), text)
        self.assertEqual(text_processing.clean_text("می\u200dروم"), "می\u200dروم")

    def test_character_proxy_and_kokoro_use_identical_generic_rules(self):
        text = "#Hello - `bonjour` 🙂 <END>"
        expected = text_processing.clean_text(text)
        self.assertEqual(expected, "Hello - bonjour")
        self.assertEqual(
            tts_text_processing.clean_text({"input": text, "model": cfg.LANGUAGE_PRACTICE.tts_model})[0], expected
        )
        value = json.loads(kokoro.speech_body(json.dumps({"input": text}).encode()))
        self.assertEqual(value["input"], expected)

    def test_empty_speech_is_rejected_before_native_inference(self):
        for text in ("", "🙂❤️", None):
            with self.subTest(text=ascii(text)), self.assertRaises(ValueError):
                text_processing.clean_speech_payload({"input": text})
        self.assertIsNone(tts_text_processing.clean_text({"input": "🙂"})[0])

    def test_breeze_only_rules_remain_in_adapter(self):
        text = '"Hello" (waves) 🙂'
        self.assertEqual(text_processing.clean_text(text), '"Hello" (waves)')
        self.assertEqual(
            tts_text_processing.clean_text({"input": text, "model": cfg.AudiocppModel.BREEZE_TTS.value})[0],
            "Hello waves",
        )


if __name__ == "__main__":
    unittest.main()
