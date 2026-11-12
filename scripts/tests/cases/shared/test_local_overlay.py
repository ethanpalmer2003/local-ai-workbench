"""The input overlay supplies voices, characters and prompts, and stays optional."""

import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.config import local_overlay
from scripts.tests.shared.paths import CasePaths


class LocalOverlayTests(unittest.TestCase):
    def test_manifest_supplies_voice_ids_and_its_chosen_default(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "voice_sources.yaml").write_text(
                "default: second\nvoices:\n  second: {}\n  first: {}\n", encoding="utf-8"
            )
            with patch.dict(local_overlay.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(local_overlay.voice_ids(), ("first", "second"))
                self.assertEqual(local_overlay.default_voice(), "second")

    def test_without_the_overlay_every_lookup_is_empty_rather_than_an_error(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.dict(local_overlay.os.environ, {"AI_INPUT_DIR": str(Path(folder) / "absent")}),
            patch.dict(local_overlay.os.environ, {"AI_VOICES_DIR": str(Path(folder) / "absent-voices")}),
        ):
            self.assertEqual(local_overlay.voice_ids(), ())
            self.assertEqual(local_overlay.default_voice(), "")
            self.assertEqual(local_overlay.character_cards(), {})
            self.assertIsNone(local_overlay.tone_prompt())

    def test_character_cards_and_tone_prompt_come_from_the_overlay(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "kobold").mkdir()
            (root / "kobold" / "scenario.txt").write_text("card", encoding="utf-8")
            (root / "kobold" / "ignore.png").write_bytes(b"x")
            (root / "prompts").mkdir()
            (root / "prompts" / "tone_tags.txt").write_text("[Tone: calm]", encoding="utf-8")
            with patch.dict(local_overlay.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(list(local_overlay.character_cards()), ["scenario"])
                self.assertEqual(local_overlay.tone_prompt(), "[Tone: calm]")

    def test_defaults_file_replaces_code_defaults_and_ignores_bad_values(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "defaults.yaml").write_text(
                'chat:\n  tts:\n    voice: chosen\n    clone_voice: not-a-bool\nimage:\n  loras: "<lora:style:0.6>"\n',
                encoding="utf-8",
            )
            with patch.dict(local_overlay.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(local_overlay.setting("chat.tts.voice", ""), "chosen")
                self.assertEqual(local_overlay.setting("image.loras", ""), "<lora:style:0.6>")
                # - absent key, wrong type and malformed file all keep the repository default
                self.assertEqual(local_overlay.setting("chat.tts.model", "repo-model"), "repo-model")
                self.assertIs(local_overlay.setting("chat.tts.clone_voice", False), False)
                self.assertEqual(local_overlay.setting("chat.tts.instruction", "none"), "none")
            (root / "defaults.yaml").write_text("chat: [unclosed\n", encoding="utf-8")
            with patch.dict(local_overlay.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(local_overlay.setting("chat.tts.voice", "repo-default"), "repo-default")

    def test_comments_are_allowed_and_strings_keep_their_slashes(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "defaults.yaml").write_text(
                "# a commented example stays out of effect\n"
                "# chat:\n#   tts:\n#     instruction: unused\n"
                'image:\n  loras: "<lora:style:0.6>"\nchat:\n  llm: http://example/model\n',
                encoding="utf-8",
            )
            with patch.dict(local_overlay.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(local_overlay.setting("image.loras", ""), "<lora:style:0.6>")
                self.assertEqual(local_overlay.setting("chat.llm", ""), "http://example/model")
                self.assertEqual(local_overlay.setting("chat.tts.instruction", "none"), "none")

    def test_the_tracked_example_manifest_carries_placeholders_only(self):
        example = Path(local_overlay.__file__).with_name("voice_sources.example.yaml")
        payload = yaml.safe_load(example.read_text(encoding="utf-8"))
        self.assertTrue(payload["voices"])
        for name, entry in payload["voices"].items():
            self.assertTrue(name.startswith("<"), name)
            self.assertTrue(entry["category"].startswith("<"), entry["category"])
            self.assertTrue(entry["url"].startswith("https://example.invalid/"), entry["url"])
            # - every field the downloader reads must be demonstrated
            self.assertEqual(
                set(entry) - {"transcripts_xlsx"},
                {"category", "url", "exclude", "selected", "count", "selection", "fallback", "superseded_by"},
            )

    def test_superseded_voices_name_their_replacement_and_stay_listed(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "voice_sources.yaml").write_text(
                "default: current\n"
                "voices:\n"
                "  current: {}\n"
                "  old:\n    superseded_by: current\n"
                "  self:\n    superseded_by: self\n"
                "  nonsense:\n    superseded_by: ''\n",
                encoding="utf-8",
            )
            with patch.dict(local_overlay.os.environ, {"AI_INPUT_DIR": str(root)}):
                self.assertEqual(local_overlay.superseded_voices(), {"old": "current"})
                # - a superseded id stays listed but sorts last, so a picker opens on a current voice
                self.assertEqual(local_overlay.voice_ids(), ("current", "nonsense", "self", "old"))
                self.assertEqual(local_overlay.default_voice(), "current")


if __name__ == "__main__":
    unittest.main()
