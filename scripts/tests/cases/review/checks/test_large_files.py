"""A tracked file past the host's per-file cap is refused before the push, not by the remote."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.review.checks import layout
from scripts.tests.shared.paths import CasePaths


class LargeFileTests(unittest.TestCase):
    def test_a_small_tree_reports_nothing(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            small = root / "small.txt"
            small.write_text("ok", encoding="utf-8")
            with patch.object(layout, "tracked_files", return_value=[small]):
                self.assertEqual(layout.large_file_issues(), [])

    def test_a_file_past_the_limit_is_named_with_its_size(self):
        with CasePaths(__file__).temporary_directory() as folder:
            big = Path(folder) / "bundle.patch"
            big.write_bytes(b"x" * (2 * layout.BYTES_PER_MIB))
            with patch.object(layout, "tracked_files", return_value=[big]):
                issues = layout.large_file_issues(limit_mib=1)
        self.assertEqual(len(issues), 1)
        self.assertIn("bundle.patch", issues[0])
        self.assertIn("2.0 MiB", issues[0])

    def test_the_limit_sits_below_the_host_cap(self):
        # - the host refuses a single file past 100 MiB, so a lower limit leaves room to act
        self.assertLess(layout.LARGE_FILE_MIB, 100)
