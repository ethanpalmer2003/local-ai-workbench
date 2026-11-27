"""Layout rules: component ownership, folder naming, limits and file placement."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.review.checks import layout


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

    def test_a_batch_outside_the_entry_point_tree_is_reported(self):
        stray = project_cfg.SCRIPTS_DIR / "tools" / "run_thing.bat"
        wrapper = project_cfg.BASE_DIR / "scripts" / "review" / "check_repo.bat"
        with patch.object(layout, "tracked_files", return_value=[stray, wrapper]):
            self.assertEqual(
                layout.batch_placement_issues(), ["Batch outside the entry-point tree: scripts/tools/run_thing.bat"]
            )

    def test_a_batch_hands_its_run_to_the_shared_runner(self):
        self.assertEqual(
            layout._batch_runner_issue(
                "bat/checks/test_full.bat", 'set "RUN_MODULE=scripts.tests.validate"\ncall "%~dp0..\\_run.bat" %*\n'
            ),
            [],
        )
        self.assertEqual(
            layout._batch_runner_issue("bat/checks/test_full.bat", 'set "RUN_MODULE=scripts.tests.validate"\n'),
            ["Batch hands no run to _run.bat: bat/checks/test_full.bat"],
        )
        self.assertEqual(
            layout._batch_runner_issue(
                "bat/checks/test_full.bat",
                'call "%~dp0..\\_run.bat" %*\n".venv\\Scripts\\python.exe" -m scripts.tests.validate\n',
            ),
            ["Batch runs the venv python itself instead of only _run.bat: bat/checks/test_full.bat"],
        )

    def test_a_comment_mentioning_the_venv_is_not_an_invocation(self):
        self.assertEqual(
            layout._batch_runner_issue(
                "bat/checks/test_full.bat",
                'rem calls .venv\\Scripts\\python.exe -m scripts.tests.validate\ncall "%~dp0..\\_run.bat" %*\n',
            ),
            [],
        )

    def test_the_runner_and_the_batches_that_cannot_delegate_run_alone(self):
        for relative in sorted(layout.BATCH_RUNS_ALONE):
            self.assertEqual(layout._batch_runner_issue(relative, '".venv\\Scripts\\python.exe" -m x\n'), [])

    def test_a_root_folder_holding_no_tracked_file_is_a_leftover(self):
        from scripts.tests.shared.paths import CasePaths

        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder) / "workspace"
            (root / "bin").mkdir(parents=True)
            (root / "data").mkdir()
            (root / "notes").mkdir()
            tracked = root / "notes" / "TODO.md"
            tracked.touch()
            with (
                patch.object(project_cfg, "BASE_DIR", root),
                patch.object(layout, "tracked_files", return_value=[tracked]),
            ):
                self.assertEqual(
                    layout.root_folder_issues(), ["Unexpected root folder: bin (no tracked file, not a runtime root)"]
                )


class TrashPathTests(unittest.TestCase):
    def _issues(self, source: str) -> list[str]:
        # - a fixture under runs/state/temp, because the rule excuses the tests tree's own trash folders
        folder = project_cfg.STATE_DIR / "temp" / "trash-path-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "MODULE.py"
        path.write_text(source, encoding="utf-8")
        try:
            with patch.object(layout, "maintained_files", return_value=[path]):
                return layout.trash_path_issues()
        finally:
            path.unlink()
            folder.rmdir()

    def test_a_second_module_building_the_trash_path_is_reported(self):
        issues = self._issues("from pathlib import Path\nTRASH = Path('C:/AI') / 'trash'\n")
        self.assertEqual(len(issues), 1)
        self.assertIn("joins a 'trash' path", issues[0])

    def test_a_path_that_only_reads_a_file_under_trash_is_left_alone(self):
        self.assertEqual(self._issues("from pathlib import Path\nNAME = 'trash/2020-01-01'\n"), [])

    def test_the_committed_tree_builds_the_trash_path_once(self):
        self.assertEqual(layout.trash_path_issues(), [])
