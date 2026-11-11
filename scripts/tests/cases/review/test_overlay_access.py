"""Overlay paths resolve in one module; a direct read anywhere else is a finding."""

import unittest
from pathlib import Path

from scripts.review import overlay_access
from scripts.tests.shared.paths import CasePaths


class OverlayAccessTests(unittest.TestCase):
    def _scan(self, relative: str, text: str) -> list[str]:
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            return overlay_access.issues(root, [Path(relative)])

    def test_direct_environment_read_is_reported(self):
        found = self._scan("scripts/launchers/example.py", 'root = os.environ.get("AI_INPUT_DIR")\n')
        self.assertEqual(len(found), 1)
        self.assertIn("AI_INPUT_DIR", found[0])

    def test_direct_project_path_read_is_reported(self):
        found = self._scan("scripts/download/example.py", "path = project_cfg.VOICES_DIR\n")
        self.assertEqual(len(found), 1)
        self.assertIn(".VOICES_DIR", found[0])

    def test_owner_module_and_declarations_are_exempt(self):
        self.assertEqual(self._scan("scripts/config/local_overlay.py", 'os.environ["AI_VOICES_DIR"]\n'), [])
        self.assertEqual(self._scan("scripts/config/project_config.py", "INPUT_DIR = DATA_DIR\n"), [])

    def test_other_file_types_are_ignored(self):
        self.assertEqual(self._scan("scripts/config/notes.md", "AI_INPUT_DIR and data/input\n"), [])


if __name__ == "__main__":
    unittest.main()
