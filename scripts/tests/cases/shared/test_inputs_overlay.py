"""The input overlay supplies voices, characters and prompts, and stays optional."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import overlay_inputs as inputs
from scripts.tests.shared.paths import CasePaths


class InputOverlayTests(unittest.TestCase):
    def test_manifest_supplies_voice_ids_and_its_chosen_default(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "voice_sources.json").write_text(
                json.dumps({"default": "second", "voices": {"second": {}, "first": {}}}), encoding="utf-8"
            )
            with patch.dict(inputs.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(inputs.voice_ids(), ("first", "second"))
                self.assertEqual(inputs.default_voice(), "second")

    def test_without_the_overlay_every_lookup_is_empty_rather_than_an_error(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.dict(inputs.os.environ, {"AI_INPUT_DIR": str(Path(folder) / "absent")}),
            patch.dict(inputs.os.environ, {"AI_VOICES_DIR": str(Path(folder) / "absent-voices")}),
        ):
            self.assertEqual(inputs.voice_ids(), ())
            self.assertEqual(inputs.default_voice(), "")
            self.assertEqual(inputs.character_cards(), {})
            self.assertIsNone(inputs.tone_prompt())

    def test_character_cards_and_tone_prompt_come_from_the_overlay(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "kobold").mkdir()
            (root / "kobold" / "scenario.txt").write_text("card", encoding="utf-8")
            (root / "kobold" / "ignore.png").write_bytes(b"x")
            (root / "prompts").mkdir()
            (root / "prompts" / "tone_tags.txt").write_text("[Tone: calm]", encoding="utf-8")
            with patch.dict(inputs.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(list(inputs.character_cards()), ["scenario"])
                self.assertEqual(inputs.tone_prompt(), "[Tone: calm]")

    def test_defaults_file_replaces_code_defaults_and_ignores_bad_values(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "defaults.json").write_text(
                json.dumps(
                    {
                        "chat": {"tts": {"voice": "chosen", "clone_voice": "not-a-bool"}},
                        "image": {"loras": "<lora:style:0.6>"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(inputs.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(inputs.setting("chat.tts.voice", ""), "chosen")
                self.assertEqual(inputs.setting("image.loras", ""), "<lora:style:0.6>")
                # - absent key, wrong type and malformed file all keep the repository default
                self.assertEqual(inputs.setting("chat.tts.model", "repo-model"), "repo-model")
                self.assertIs(inputs.setting("chat.tts.clone_voice", False), False)
                self.assertEqual(inputs.setting("chat.tts.instruction", "none"), "none")
            (root / "defaults.json").write_text("{not json", encoding="utf-8")
            with patch.dict(inputs.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(inputs.setting("chat.tts.voice", "repo-default"), "repo-default")

    def test_comments_are_allowed_and_strings_keep_their_slashes(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "defaults.json").write_text(
                "{\n  // a commented example stays out of effect\n"
                '  // "chat": {"tts": {"instruction": "unused"}},\n'
                '  "image": {"loras": "<lora:style:0.6>"},\n'
                '  "chat": {"llm": "http://example/model"}\n}\n',
                encoding="utf-8",
            )
            with patch.dict(inputs.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(inputs.setting("image.loras", ""), "<lora:style:0.6>")
                self.assertEqual(inputs.setting("chat.llm", ""), "http://example/model")
                self.assertEqual(inputs.setting("chat.tts.instruction", "none"), "none")

    def test_the_tracked_example_manifest_carries_placeholders_only(self):
        example = Path(inputs.__file__).with_name("voice_sources.example.json")
        payload = json.loads(example.read_text(encoding="utf-8"))
        self.assertTrue(payload["voices"])
        for name, entry in payload["voices"].items():
            self.assertTrue(name.startswith("<"), name)
            self.assertTrue(entry["category"].startswith("<"), entry["category"])
            self.assertTrue(entry["url"].startswith("https://example.invalid/"), entry["url"])
            # - every field the downloader reads must be demonstrated
            self.assertEqual(
                set(entry) - {"transcripts_xlsx"},
                {"category", "url", "exclude", "selected", "count", "selection", "fallback"},
            )


if __name__ == "__main__":
    unittest.main()
