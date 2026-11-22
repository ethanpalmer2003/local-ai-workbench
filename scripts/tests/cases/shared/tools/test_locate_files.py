"""The depth-bounded locator stops at its depth, skips hidden folders and names a miss."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.tests.shared.paths import CasePaths
from scripts.tools import locate_files


class LocateTests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        (root / "a/b").mkdir(parents=True)
        (root / "top.gguf").write_bytes(b"x")
        (root / "a/mid.GGUF").write_bytes(b"x")
        (root / "a/b/deep.gguf").write_bytes(b"x")
        (root / ".hidden").mkdir()
        (root / ".hidden/skip.gguf").write_bytes(b"x")

    def test_matches_are_found_to_the_configured_depth_only(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            self._tree(root)
            names = sorted(path.name for path in locate_files.locate([".gguf"], [root], depth=2))
        self.assertEqual(names, ["mid.GGUF", "top.gguf"])

    def test_a_missing_root_is_ignored(self):
        with CasePaths(__file__).temporary_directory() as folder:
            found = locate_files.locate([".gguf"], [Path(folder) / "absent"], depth=4)
        self.assertEqual(found, [])

    def test_main_names_a_miss_and_returns_one(self):
        output = io.StringIO()
        with patch.object(locate_files, "locate", return_value=[]), redirect_stdout(output):
            status = locate_files.main([".gguf"])
        self.assertEqual(status, 1)
        self.assertIn("no file under", output.getvalue())

    def test_main_prints_a_path_and_returns_zero(self):
        output = io.StringIO()
        with patch.object(locate_files, "locate", return_value=[Path("weights.gguf")]), redirect_stdout(output):
            status = locate_files.main([".gguf"])
        self.assertEqual(status, 0)
        self.assertIn("weights.gguf", output.getvalue())


if __name__ == "__main__":
    unittest.main()
