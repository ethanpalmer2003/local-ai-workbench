"""Typographic dash rejection: em-dash and en-dash detection, and the corpus masking that keeps it honest."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import dashes


class ScanTests(unittest.TestCase):
    def test_an_em_dash_is_reported_with_its_line(self):
        self.assertEqual(dashes.scan_text("notes.md", "first line\nsecond \u2014 dash\n"), [(2, "em-dash")])

    def test_an_en_dash_is_reported_as_its_own_kind(self):
        self.assertEqual(dashes.scan_text("notes.md", "27.6\u201334.1\n"), [(1, "en-dash")])

    def test_plain_hyphens_and_commas_pass(self):
        self.assertEqual(dashes.scan_text("notes.md", "27.6-34.1, fine - still fine\n"), [])

    def test_quoted_corpus_references_are_masked_and_the_rest_of_the_file_is_not(self):
        text = '{"clips": [{"reference": "a \u2014 b", "id": "x"}],\n "note": "kept \u2013 scan"\n}'
        self.assertEqual(dashes.scan_text(dashes.REFERENCE_FILE, text), [(2, "en-dash")])

    def test_an_escaped_reference_still_masks_cleanly(self):
        text = '{"reference": "quote \\" \u2014 inside"}\n"other": "\u2014"\n'
        self.assertEqual(dashes.scan_text(dashes.REFERENCE_FILE, text), [(2, "em-dash")])

    def test_masking_keeps_the_width_of_the_value_it_hides(self):
        line = '{"reference": "\u2014\u2014"}'
        self.assertEqual(len(dashes.masked(line, dashes.REFERENCE_FILE)), len(line))


class CheckTests(unittest.TestCase):
    def run_check(self, names: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = dashes.check(project_cfg.BASE_DIR, names)
        return status, stream.getvalue()

    def test_a_clean_file_passes(self):
        status, printed = self.run_check(["scripts/review/dashes.py"])
        self.assertEqual(status, 0)
        self.assertIn("0 typographic dash(es)", printed)

    def test_a_file_with_a_dash_fails_and_names_the_line(self):
        with self.subTest():
            target = Path(project_cfg.BASE_DIR) / "scripts/tests/output/dash-fixture.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("line\nbad \u2014 dash\n", encoding="utf-8")
            try:
                status, printed = self.run_check(["scripts/tests/output/dash-fixture.md"])
            finally:
                target.unlink()
        self.assertEqual(status, 1)
        self.assertIn("dash-fixture.md:2: em-dash", printed)


class SuffixTests(unittest.TestCase):
    def test_prose_and_config_are_text_but_weights_are_not(self):
        self.assertTrue(dashes.is_text("README.md"))
        self.assertTrue(dashes.is_text("scripts/launchers/launcher_config.py"))
        self.assertTrue(dashes.is_text("scripts/config/benchmarks/language_corpus.json"))
        self.assertTrue(dashes.is_text("scripts/tests/ui/speech.html"))
        self.assertTrue(dashes.is_text("scripts/tests/notes/asr/leaderboards-2026-10-29/table-15.csv"))
        self.assertFalse(dashes.is_text("data/huggingface/models/llms/character_models/x.gguf"))
        self.assertFalse(dashes.is_text("frameworks/llamacpp/llama-server.exe"))


if __name__ == "__main__":
    unittest.main()
