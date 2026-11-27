"""The path check flags hand-spelled config paths and passes the owner and clean code."""

import tempfile
import unittest
from pathlib import Path

from scripts.review.lists import hardcoded_paths


class HardcodedPathTests(unittest.TestCase):
    def _findings(self, name: str, body: str) -> list[hardcoded_paths.Finding]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_text(body, encoding="utf-8")
            return hardcoded_paths.findings([path])

    def test_a_joined_literal_naming_a_owned_tree_fails(self):
        found = self._findings("module.py", 'path = root / "state" / "logs"\n')
        self.assertEqual([item.line for item in found], [1])
        self.assertIn("state/logs", found[0].detail)

    def test_a_string_naming_an_owned_tree_fails_in_any_scanned_file(self):
        found = self._findings("comment.bat", "rem reports land under runs/tests/output\n")
        self.assertEqual(len(found), 1)

    def test_a_component_name_that_merely_contains_an_owned_tree_passes(self):
        found = self._findings("module.py", "A = 'download/frameworks/llamacpp/local-work'\n")
        self.assertEqual(found, [])

    def test_a_docstring_naming_a_path_fails_like_any_other_string(self):
        found = self._findings("module.py", '"""Writes under runs/state/generated; see the owner."""\nX = 1\n')
        self.assertEqual(len(found), 1)

    def test_a_docstring_that_names_the_owner_passes(self):
        found = self._findings("module.py", '"""Writes under the generated root; see project_config."""\nX = 1\n')
        self.assertEqual(found, [])

    def test_importing_the_constant_passes(self):
        self.assertEqual(self._findings("module.py", "path = project_cfg.STATE_DIR / 'logs'\n"), [])

    def test_the_owner_and_a_test_path_are_not_flagged_for_their_own_names(self):
        with tempfile.TemporaryDirectory() as folder:
            owner = Path(folder) / "project_config.py"
            owner.write_text('STATE_DIR = BASE_DIR / "scripts" / "state"\n', encoding="utf-8")
            found = hardcoded_paths.findings([owner])
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
