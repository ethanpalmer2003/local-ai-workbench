"""Strata profile junction checks and the merge helper; nothing touches the real profile."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tools import strata_profile


class StrataProfileLinkTests(unittest.TestCase):
    def test_merge_replaces_collisions_and_keeps_extra_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source"
            target = Path(folder) / "target"
            (source / "sub").mkdir(parents=True)
            (source / "sub" / "a.txt").write_text("new", encoding="utf-8")
            (target / "sub").mkdir(parents=True)
            (target / "sub" / "a.txt").write_text("old", encoding="utf-8")
            (target / "b.txt").write_text("keep", encoding="utf-8")
            strata_profile._merge(source, target)
            self.assertFalse(source.exists())
            self.assertEqual((target / "sub" / "a.txt").read_text(encoding="utf-8"), "new")
            self.assertEqual((target / "b.txt").read_text(encoding="utf-8"), "keep")

    def test_a_missing_profile_folder_is_reported(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(strata_profile, "LOCAL", Path(folder)):
            self.assertEqual(strata_profile.state("Strata"), "missing")

    def test_a_real_folder_is_reported_as_real(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "Strata").mkdir()
            with patch.object(strata_profile, "LOCAL", Path(folder)):
                self.assertEqual(strata_profile.state("Strata"), "real")


if __name__ == "__main__":
    unittest.main()
