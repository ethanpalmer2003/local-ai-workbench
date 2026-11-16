"""Gate scoping: an empty change set runs every section, a change runs only what it reaches."""

import unittest
from unittest.mock import patch


class GateScopeTests(unittest.TestCase):
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
        from scripts.shared import changes

        def git(*args: str, **_: object) -> str:
            if args[0] == "status":
                return "R  bat/tests/a.bat -> bat/checks/a.bat\n M notes/TODO.md\n"
            return "scripts/tools/older.py\n"

        with patch.object(changes, "git", side_effect=git):
            self.assertEqual(
                changes.changed_paths(),
                ["bat/checks/a.bat", "bat/tests/a.bat", "notes/TODO.md", "scripts/tools/older.py"],
            )

    def test_an_empty_change_set_falls_back_to_every_section(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=[]),
            patch.object(gate, "full_gate", return_value=0) as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            gate.main([])
        full.assert_called_once()
        touched.assert_not_called()

    def test_a_change_runs_only_the_touched_sections(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=["notes/TODO.md"]),
            patch.object(gate, "full_gate") as full,
            patch.object(gate, "touched_gate", return_value=0) as touched,
        ):
            gate.main([])
        touched.assert_called_once()
        full.assert_not_called()

    def test_all_runs_every_section_whatever_changed(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_paths", return_value=["notes/TODO.md"]),
            patch.object(gate, "full_gate", return_value=0) as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            gate.main(["--all"])
        full.assert_called_once()
        touched.assert_not_called()

    def test_formatting_targets_the_change_and_falls_back_to_the_tree(self):
        from scripts.review import format_py

        with patch.object(format_py, "changed_paths", return_value=["notes/TODO.md", "scripts/tools/a.py"]):
            self.assertEqual(format_py.python_targets(False), ["scripts/tools/a.py"])
        with patch.object(format_py, "changed_paths", return_value=["notes/TODO.md"]):
            self.assertEqual(format_py.python_targets(False), ["."])
        self.assertEqual(format_py.python_targets(True), ["."])


if __name__ == "__main__":
    unittest.main()
