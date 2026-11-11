"""Layout rules: component ownership, folder naming, limits and file placement."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.review import layout


class PolicyTests(unittest.TestCase):
    def test_documented_complexity_limit_matches_config(self):
        self.assertEqual(layout.policy_limit_issues(), [])

    def test_a_file_without_a_role_in_a_high_level_folder_is_rejected(self):
        self.assertEqual(
            layout._placement_issues(project_cfg.BASE_DIR / "stray.txt"),
            ["File has no place in the workspace root: stray.txt"],
        )
        self.assertEqual(
            layout._placement_issues(project_cfg.BASE_DIR / "notes" / "stray.py"),
            ["File has no place in notes: stray.py"],
        )

    def test_a_role_tree_rejects_an_unexpected_type_at_depth(self):
        self.assertEqual(
            layout._placement_issues(project_cfg.BASE_DIR / "scripts/config/models/stray.exe"),
            ["File has no place in scripts/config/models: stray.exe"],
        )
        self.assertEqual(
            layout._placement_issues(project_cfg.BASE_DIR / "bat/browser/stray.json"),
            ["File has no place in bat/browser: stray.json"],
        )

    def test_known_root_files_and_role_types_pass(self):
        self.assertIsNone(layout._placement_issues(project_cfg.BASE_DIR / "README.md"))
        self.assertIsNone(layout._placement_issues(project_cfg.BASE_DIR / "notes" / "TODO.md"))
        self.assertIsNone(layout._placement_issues(project_cfg.BASE_DIR / "scripts/config/models/catalog.json"))
        self.assertIsNone(layout._placement_issues(project_cfg.BASE_DIR / "bat/browser/comfyui/launch_comfyui.bat"))

    def test_placement_reads_tracked_files_only(self):
        stray = project_cfg.BASE_DIR / "stray.txt"
        with patch.object(layout, "tracked_files", return_value=[stray]):
            self.assertEqual(layout.placement_issues(), ["File has no place in the workspace root: stray.txt"])
        with patch.object(layout, "tracked_files", return_value=[]):
            self.assertEqual(layout.placement_issues(), [])

    def test_a_package_holding_only_an_empty_init_is_a_placeholder(self):
        from scripts.tests.shared.paths import CasePaths

        with CasePaths(__file__).temporary_directory() as folder:
            package = Path(folder) / "package"
            package.mkdir()
            init = package / "__init__.py"
            init.touch()
            with patch.object(layout, "tracked_files", return_value=[init]):
                self.assertEqual(
                    layout.empty_shell_issues(),
                    [f"Empty package shell: {package.relative_to(project_cfg.BASE_DIR).as_posix()}"],
                )
