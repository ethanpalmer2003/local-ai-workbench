"""Full review gate consent: an unattended run refuses, a person at the terminal answers the question."""

import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from scripts.review import __main__ as review


class ConsentTests(unittest.TestCase):
    def test_yes_flag_confirms_without_a_terminal(self):
        with patch("scripts.review.__main__.sys.stdin", Mock(isatty=lambda: False)):
            self.assertTrue(review.consents(True))

    def test_unattended_run_is_refused_and_says_why(self):
        printed = io.StringIO()
        with (
            patch("scripts.review.__main__.sys.stdin", Mock(isatty=lambda: False)),
            contextlib.redirect_stdout(printed),
        ):
            self.assertFalse(review.consents(False))
        self.assertIn("needs the user's agreement", printed.getvalue())

    def test_person_at_the_terminal_answers_the_question(self):
        cases = (("yes", True), (" YES ", True), ("no", False), ("", False))
        for answer, expected in cases:
            with (
                patch("scripts.review.__main__.sys.stdin", Mock(isatty=lambda: True)),
                patch("builtins.input", return_value=answer),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(review.consents(False), expected, answer)

    def test_a_batch_rename_only_needs_layout_and_docs(self):
        from scripts.review.__main__ import touched_sections

        self.assertEqual(touched_sections(["bat/checks/test_full.bat"]), {"layout", "docs"})

    def test_a_python_edit_adds_the_code_sections(self):
        from scripts.review.__main__ import touched_sections

        sections = touched_sections(["scripts/tools/example.py"])
        self.assertTrue({"layout", "docs", "lint", "types", "dead code"} <= sections)
        self.assertNotIn("spelling", sections)

    def test_a_markdown_edit_adds_the_prose_sections_without_code_ones(self):
        from scripts.review.__main__ import touched_sections

        sections = touched_sections(["notes/TODO.md"])
        self.assertTrue({"docs", "typography", "spelling"} <= sections)
        self.assertNotIn("lint", sections)

    def test_a_rename_reports_both_paths_from_git_status(self):
        from scripts.review.__main__ import changed_paths

        completed = Mock(stdout="R  bat/tests/a.bat -> bat/checks/a.bat\n M notes/TODO.md\n")
        with patch("scripts.review.__main__.subprocess.run", return_value=completed):
            self.assertEqual(changed_paths(), ["bat/tests/a.bat", "bat/checks/a.bat", "notes/TODO.md"])


if __name__ == "__main__":
    unittest.main()
