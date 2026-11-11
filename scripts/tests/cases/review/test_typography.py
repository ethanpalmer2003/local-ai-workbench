"""Typographic substitutes: detection per kind, and the corpus masking that keeps the check honest."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import typography


class ScanTests(unittest.TestCase):
    def test_an_em_dash_is_reported_with_its_line(self):
        self.assertEqual(typography.scan_text("notes.md", "first line\nsecond \u2014 dash\n"), [(2, "em-dash")])

    def test_an_en_dash_is_reported_as_its_own_kind(self):
        self.assertEqual(typography.scan_text("notes.md", "27.6\u201334.1\n"), [(1, "en-dash")])

    def test_curly_quotes_and_the_ellipsis_are_named(self):
        text = "He said \u201chello\u201d and \u2018left\u2019\u2026\n"
        kinds = [kind for _, kind in typography.scan_text("notes.md", text)]
        self.assertEqual(
            kinds, ["left-double-quote", "right-double-quote", "left-single-quote", "right-single-quote", "ellipsis"]
        )

    def test_no_break_spaces_and_soft_hyphens_are_named(self):
        text = "a\u00a0b c\u202fd e\u00adf\n"
        kinds = [kind for _, kind in typography.scan_text("notes.md", text)]
        self.assertEqual(kinds, ["no-break-space", "narrow-no-break-space", "soft-hyphen"])

    def test_plain_ascii_punctuation_passes(self):
        self.assertEqual(typography.scan_text("notes.md", '27.6-34.1, "quoted", three dots... and a space\n'), [])

    def test_quoted_corpus_references_are_masked_and_the_rest_of_the_file_is_not(self):
        text = '{"clips": [{"reference": "a \u2014 b"}],\n "note": "kept \u2013 scan"\n}'
        self.assertEqual(typography.scan_text(typography.REFERENCE_FILE, text), [(2, "en-dash")])

    def test_an_escaped_reference_still_masks_cleanly(self):
        text = '{"reference": "quote \\" \u2014 inside"}\n"other": "\u2014"\n'
        self.assertEqual(typography.scan_text(typography.REFERENCE_FILE, text), [(2, "em-dash")])

    def test_masking_keeps_the_width_of_the_value_it_hides(self):
        line = '{"reference": "\u2014\u2014\u2026"}'
        self.assertEqual(len(typography.masked(line, typography.REFERENCE_FILE)), len(line))


class CheckTests(unittest.TestCase):
    def run_check(self, names: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = typography.check(project_cfg.BASE_DIR, names)
        return status, stream.getvalue()

    def test_a_clean_file_passes(self):
        status, printed = self.run_check(["scripts/review/typography.py"])
        self.assertEqual(status, 0)
        self.assertIn("0 typographic character(s)", printed)

    def test_a_file_with_an_ellipsis_fails_and_names_the_line(self):
        target = Path(project_cfg.BASE_DIR) / "scripts/tests/output/typography-fixture.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line\nbad\u2026 dots\n", encoding="utf-8")
        try:
            status, printed = self.run_check(["scripts/tests/output/typography-fixture.md"])
        finally:
            target.unlink()
        self.assertEqual(status, 1)
        self.assertIn("typography-fixture.md:2: ellipsis", printed)


class SuffixTests(unittest.TestCase):
    def test_prose_and_config_are_text_but_weights_are_not(self):
        self.assertTrue(typography.is_text("README.md"))
        self.assertTrue(typography.is_text("scripts/launchers/launcher_config.py"))
        self.assertTrue(typography.is_text("scripts/config/benchmarks/language_corpus.json"))
        self.assertTrue(typography.is_text("scripts/tests/ui/speech.html"))
        self.assertTrue(typography.is_text("scripts/tests/notes/asr/leaderboards-2026-10-29/table-15.csv"))
        self.assertFalse(typography.is_text("data/huggingface/models/llms/character_models/x.gguf"))
        self.assertFalse(typography.is_text("frameworks/llamacpp/llama-server.exe"))


if __name__ == "__main__":
    unittest.main()
