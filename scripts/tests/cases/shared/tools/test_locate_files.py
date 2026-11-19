"""The bounded locator finds a file at the depth it was told, and nowhere deeper."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.tools.locate_files import locate


def _weights(root: Path, depth: int) -> Path:
    """Create `depth` nested folders under `root` and put one weights file at the bottom."""
    folder = root
    for level in range(depth):
        folder = folder / f"level{level}"
    folder.mkdir(parents=True)
    weights = folder / "model.gguf"
    weights.write_bytes(b"x")
    return weights


class LocateFileTests(unittest.TestCase):
    def test_a_file_at_the_depth_limit_is_found(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = _weights(root, 2)
            self.assertEqual(locate([".gguf"], [root], depth=3), [weights])

    def test_a_file_past_the_depth_limit_is_not_found(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _weights(root, 3)
            self.assertEqual(locate([".gguf"], [root], depth=3), [])

    def test_the_suffix_match_ignores_case(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Model.GGUF").write_bytes(b"x")
            self.assertEqual(locate([".gguf"], [root]), [root / "Model.GGUF"])

    def test_a_hidden_folder_is_skipped(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            hidden = root / ".cache"
            hidden.mkdir()
            (hidden / "model.gguf").write_bytes(b"x")
            self.assertEqual(locate([".gguf"], [root]), [])

    def test_a_missing_root_is_ignored(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(locate([".gguf"], [root / "absent"]), [])
