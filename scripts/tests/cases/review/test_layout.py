"""Layout rules: component ownership, folder naming, limits and file placement."""

import unittest
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.review import layout


class PolicyTests(unittest.TestCase):
    def test_documented_complexity_limit_matches_config(self):
        self.assertEqual(layout.policy_limit_issues(), [])

    def test_a_file_without_a_role_in_a_high_level_folder_is_rejected(self):
        self.assertEqual(
            layout._placement_issues(project_cfg.BASE_DIR / "stray.txt"), ["File has no place in AI: stray.txt"]
        )
        self.assertEqual(
            layout._placement_issues(project_cfg.BASE_DIR / "notes" / "stray.py"),
            ["File has no place in notes: stray.py"],
        )

    def test_known_root_files_and_role_suffixes_pass(self):
        self.assertIsNone(layout._placement_issues(project_cfg.BASE_DIR / "README.md"))
        self.assertIsNone(layout._placement_issues(project_cfg.BASE_DIR / "notes" / "TODO.md"))

    def test_placement_reads_tracked_files_only(self):
        stray = project_cfg.BASE_DIR / "stray.txt"
        with patch.object(layout, "tracked_files", return_value=[stray]):
            self.assertEqual(layout.placement_issues(), ["File has no place in AI: stray.txt"])
        with patch.object(layout, "tracked_files", return_value=[]):
            self.assertEqual(layout.placement_issues(), [])
