"""A single-owner token fails the gate when a second module spells it."""

import tempfile
import unittest
from pathlib import Path

from scripts.review import owned_tokens
from scripts.review.owned_tokens import Rule


class OwnedTokenTests(unittest.TestCase):
    def _findings(self, files: dict[str, str], owners: set[str]) -> list[tuple[str, str, int]]:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, text in files.items():
                (root / name).write_text(text, encoding="utf-8")
            paths = [root / name for name in files]
            owned = {owned_tokens._relative(root / name) for name in owners}
            return owned_tokens.findings(paths, (Rule("--yes", frozenset(owned), "test"),))

    def test_a_second_copy_outside_the_owner_is_reported(self):
        found = self._findings({"owner.py": 'FLAG = "--yes"\n', "copy.py": 'x = "--yes"\n'}, {"owner.py"})
        self.assertEqual([(token, path.rsplit("/", 1)[-1]) for token, path, _ in found], [("--yes", "copy.py")])

    def test_the_owner_may_spell_it_anywhere(self):
        found = self._findings({"owner.py": '"""Mentions --yes twice: --yes."""\nFLAG = "--yes"\n'}, {"owner.py"})
        self.assertEqual(found, [])

    def test_a_batch_file_is_scanned_textually(self):
        found = self._findings({"owner.bat": "call run.bat\n", "stop.bat": "call run.bat --yes\n"}, {"owner.bat"})
        self.assertEqual([(token, path.rsplit("/", 1)[-1]) for token, path, _ in found], [("--yes", "stop.bat")])

    def test_non_python_and_non_batch_files_are_ignored(self):
        found = self._findings({"notes.md": "pass --yes\n"}, set())
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
