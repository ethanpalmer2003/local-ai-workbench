"""Typographic substitutes: detection per kind, and the corpus masking that keeps the check honest."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.review.checks import typography
from scripts.review.lists import text_files
from scripts.shared import file_sets


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

    def test_a_control_character_is_named_by_its_code_point(self):
        self.assertEqual(
            typography.scan_text("notes.md", "keep \u0007rgv and \u000bocabulary\n"),
            [(1, "control-character U+0007"), (1, "control-character U+000B")],
        )

    def test_an_indent_tab_passes_because_a_patch_and_a_ts_file_keep_one(self):
        self.assertEqual(typography.scan_text("scripts/config/coding_agents/pi/x.ts", "\tlet p = 1;\n"), [])

    def test_quoted_corpus_references_are_masked_and_the_rest_of_the_file_is_not(self):
        text = '{"clips": [{"reference": "a \u2014 b"}],\n "note": "kept \u2013 scan"\n}'
        self.assertEqual(typography.scan_text(text_files.CORPUS_FILE, text), [(2, "en-dash")])

    def test_an_escaped_reference_still_masks_cleanly(self):
        text = '{"reference": "quote \\" \u2014 inside"}\n"other": "\u2014"\n'
        self.assertEqual(typography.scan_text(text_files.CORPUS_FILE, text), [(2, "em-dash")])

    def test_masking_keeps_the_width_of_the_value_it_hides(self):
        line = '{"reference": "\u2014\u2014\u2026"}'
        self.assertEqual(len(text_files.mask_corpus_references(text_files.CORPUS_FILE, line)), len(line))

    def test_a_spaced_dash_between_words_is_reported_from_a_docstring(self):
        text = 'def f():\n    """Keep this - never that."""\n'
        self.assertEqual(typography.prose_dashes("scripts/a.py", text), [(2, "prose-dash")])

    def test_a_bullet_a_comment_marker_and_arithmetic_stay_legal(self):
        text = 'def f():\n    """First line.\n\n    - a bullet\n    """\n# - a marker\nVALUE = 1 - 2\n'
        self.assertEqual(typography.prose_dashes("scripts/a.py", text), [])

    def test_a_prose_dash_in_a_comment_is_reported(self):
        self.assertEqual(
            typography.prose_dashes("scripts/a.py", "x = 1  # keep this - never that\n"), [(1, "prose-dash")]
        )

    def test_only_python_is_scanned_for_prose_dashes(self):
        self.assertEqual(typography.prose_dashes("notes.md", "one - two"), [])


class CheckTests(unittest.TestCase):
    def run_check(self, names: list[str]) -> tuple[int, str]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = typography.check(project_cfg.BASE_DIR, names)
        return status, stream.getvalue()

    def test_a_clean_file_passes(self):
        status, printed = self.run_check(["scripts/review/checks/typography.py"])
        self.assertEqual(status, 0)
        self.assertIn("0 unpublishable character(s)", printed)

    def test_a_file_with_an_ellipsis_fails_and_names_the_line(self):
        target = project_cfg.TEST_OUTPUT_DIR / "typography-fixture.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line\nbad\u2026 dots\n", encoding="utf-8")
        try:
            status, printed = self.run_check([target.relative_to(project_cfg.BASE_DIR).as_posix()])
        finally:
            target.unlink()
        self.assertEqual(status, 1)
        self.assertIn("typography-fixture.md:2: ellipsis", printed)


class TargetTests(unittest.TestCase):
    def targets(self, argv: list[str], skip: set[str] | None = None) -> tuple[Path, list[str]]:
        with (
            patch.object(file_sets, "git_root", return_value=Path("/repo")),
            patch.object(file_sets, "tracked_text_files", return_value=["a.md", "b.py"]),
        ):
            return text_files.text_check_targets(argv, "check", skip or set())

    def test_no_paths_means_every_tracked_text_file(self):
        self.assertEqual(self.targets([]), (Path("/repo"), ["a.md", "b.py"]))

    def test_named_paths_replace_the_default_set_and_still_drop_a_skipped_one(self):
        self.assertEqual(self.targets(["a.md", "own.py"], {"own.py"}), (Path("/repo"), ["a.md"]))


class SuffixTests(unittest.TestCase):
    def test_prose_and_config_are_text_but_weights_are_not(self):
        self.assertTrue(file_sets.is_text("README.md"))
        self.assertTrue(file_sets.is_text("scripts/launchers/launcher_config.py"))
        self.assertTrue(file_sets.is_text("scripts/config/benchmarks/language_corpus.json"))
        self.assertTrue(file_sets.is_text("scripts/tests/ui/speech.html"))
        self.assertTrue(file_sets.is_text("scripts/tests/notes/asr/leaderboards-2026-10-29/table-15.csv"))
        self.assertFalse(file_sets.is_text("data/huggingface/models/llms/character_models/x.gguf"))
        self.assertFalse(file_sets.is_text("frameworks/llamacpp/llama-server.exe"))


if __name__ == "__main__":
    unittest.main()
