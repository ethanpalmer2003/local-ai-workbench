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

    def test_changed_paths_cover_the_working_tree_and_unpushed_commits(self):
        from scripts.review.__main__ import changed_paths

        def git(*args: str) -> str:
            if args[0] == "status":
                return "R  bat/tests/a.bat -> bat/checks/a.bat\n M notes/TODO.md\n"
            return "scripts/tools/older.py\n"

        with patch("scripts.review.__main__._git", side_effect=git):
            self.assertEqual(
                changed_paths(), ["bat/checks/a.bat", "bat/tests/a.bat", "notes/TODO.md", "scripts/tools/older.py"]
            )

    def test_an_empty_change_set_falls_back_to_every_section(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=[]),
            patch.object(gate, "full_gate", return_value=0) as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            gate.main(["--yes"])
        full.assert_called_once()
        touched.assert_not_called()

    def test_a_change_runs_only_the_touched_sections(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=["notes/TODO.md"]),
            patch.object(gate, "full_gate") as full,
            patch.object(gate, "touched_gate", return_value=0) as touched,
        ):
            gate.main(["--yes"])
        touched.assert_called_once()
        full.assert_not_called()

    def test_all_runs_every_section_whatever_changed(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=["notes/TODO.md"]),
            patch.object(gate, "full_gate", return_value=0) as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            gate.main(["--yes", "--all"])
        full.assert_called_once()
        touched.assert_not_called()

    def test_a_repo_wide_run_without_agreement_runs_nothing(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=[]),
            patch.object(gate, "consents", return_value=False),
            patch.object(gate, "full_gate") as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            self.assertEqual(gate.main([]), 1)
        full.assert_not_called()
        touched.assert_not_called()

    def test_a_scoped_run_does_not_ask(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=["notes/TODO.md"]),
            patch.object(gate, "consents") as consent,
            patch.object(gate, "touched_gate", return_value=0) as touched,
        ):
            self.assertEqual(gate.main([]), 0)
        consent.assert_not_called()
        touched.assert_called_once()

    def test_formatting_targets_the_change_and_falls_back_to_the_tree(self):
        from scripts.review import format_py

        with patch.object(format_py, "changed_paths", return_value=["notes/TODO.md", "scripts/tools/a.py"]):
            self.assertEqual(format_py.python_targets(False), ["scripts/tools/a.py"])
        with patch.object(format_py, "changed_paths", return_value=["notes/TODO.md"]):
            self.assertEqual(format_py.python_targets(False), ["."])
        self.assertEqual(format_py.python_targets(True), ["."])


if __name__ == "__main__":
    unittest.main()
