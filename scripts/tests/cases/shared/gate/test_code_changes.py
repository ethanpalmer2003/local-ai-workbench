"""The code-change question: a prose-only Python edit is not a change, a real one is."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.shared import code_changes
from scripts.tests.shared.paths import CasePaths


class CodeChangeStageTests(unittest.TestCase):
    """The push stage asks the same question the commit stage asks: did any code change?"""

    def _tree(self, folder: str, current: str) -> Path:
        root = Path(folder)
        (root / "scripts").mkdir()
        (root / "scripts" / "run.py").write_text(current, encoding="utf-8")
        return root

    def test_a_docstring_only_edit_is_not_a_code_change(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = self._tree(folder, '"""New docstring."""\nVALUE = 1\n')
            with patch.object(
                code_changes, "upstream_texts", return_value={"scripts/run.py": '"""Old docstring."""\nVALUE = 1\n'}
            ):
                self.assertEqual(code_changes.code_change_paths(["scripts/run.py"], root), [])

    def test_a_code_edit_is_a_code_change(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = self._tree(folder, '"""New docstring."""\nVALUE = 2\n')
            with patch.object(
                code_changes, "upstream_texts", return_value={"scripts/run.py": '"""Old docstring."""\nVALUE = 1\n'}
            ):
                self.assertEqual(code_changes.code_change_paths(["scripts/run.py"], root), ["scripts/run.py"])

    def test_a_deleted_file_and_a_document_are_changes(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = self._tree(folder, "VALUE = 1\n")
            with patch.object(code_changes, "upstream_texts", return_value={}):
                self.assertEqual(
                    code_changes.code_change_paths(["notes/TODO.md", "scripts/removed.py"], root),
                    ["notes/TODO.md", "scripts/removed.py"],
                )

    def test_a_document_or_a_batch_file_does_not_count_for_the_push(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = self._tree(folder, "VALUE = 1\n")
            with patch.object(code_changes, "upstream_texts", return_value={}) as upstream:
                self.assertFalse(code_changes.python_code_changed(["notes/TODO.md", "bat/checks/a.bat"], root))
            upstream.assert_not_called()

    def test_a_docstring_only_python_edit_does_not_count_for_the_push(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = self._tree(folder, '"""New docstring."""\nVALUE = 1\n')
            with patch.object(
                code_changes, "upstream_texts", return_value={"scripts/run.py": '"""Old docstring."""\nVALUE = 1\n'}
            ):
                self.assertFalse(code_changes.python_code_changed(["scripts/run.py", "notes/TODO.md"], root))

    def test_a_python_code_edit_counts_for_the_push(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = self._tree(folder, '"""New docstring."""\nVALUE = 2\n')
            with patch.object(
                code_changes, "upstream_texts", return_value={"scripts/run.py": '"""Old docstring."""\nVALUE = 1\n'}
            ):
                self.assertTrue(code_changes.python_code_changed(["notes/TODO.md", "scripts/run.py"], root))

    def test_an_unreadable_upstream_copy_counts_as_a_change(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = self._tree(folder, "VALUE = 1\n")
            with patch.object(code_changes, "upstream_texts", side_effect=code_changes.GitError("no git")):
                self.assertEqual(code_changes.code_change_paths(["scripts/run.py"], root), ["scripts/run.py"])


if __name__ == "__main__":
    unittest.main()
