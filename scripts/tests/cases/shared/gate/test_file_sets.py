"""The file sets nest: every text file and every maintained file is a tracked file."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.shared import file_sets


def _write(root: Path, name: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content\n", encoding="utf-8")


class NestingTests(unittest.TestCase):
    def test_every_tracked_text_file_is_in_the_tracked_set(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("a.md", "scripts/b.py", "bin/c.exe"):
                _write(root, name)
            listed = ["a.md", "scripts/b.py", "bin/c.exe", "gone.md"]
            with patch.object(file_sets, "git_ls_files", return_value=listed):
                # - c.exe is binary and gone.md is deleted, so only the two text files survive
                self.assertEqual(set(file_sets.tracked_text_files(root)), {"a.md", "scripts/b.py"})
                self.assertLessEqual(set(file_sets.tracked_text_files(root)), set(listed))

    def test_every_maintained_file_is_in_the_tracked_set(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            scripts_dir, bat_dir = base / "scripts", base / "bat"
            for name in ("top.md", "scripts/a.py", "bat/b.bat", "notes/c.md", ".agents/d.md"):
                _write(base, name)
            _write(base, "scripts/parked/e.py")
            _write(base, "scripts/f.txt")
            with (
                patch.object(project_cfg, "BASE_DIR", base),
                patch.object(project_cfg, "SCRIPTS_DIR", scripts_dir),
                patch.object(project_cfg, "BAT_DIR", bat_dir),
            ):
                maintained = {path.relative_to(base).as_posix() for path in file_sets.maintained_files()}
                self.assertEqual(maintained, {"top.md", "scripts/a.py", "bat/b.bat", "notes/c.md", ".agents/d.md"})
                with patch.object(file_sets, "git_ls_files", return_value=sorted(maintained)):
                    tracked = {path.relative_to(base).as_posix() for path in file_sets.tracked_files()}
            self.assertLessEqual(maintained, tracked)


if __name__ == "__main__":
    unittest.main()
