"""The folder rule: one file and nothing else fails, a sparse folder is only a merge candidate."""

import unittest
from pathlib import Path

from scripts.review.checks import inventory_code
from scripts.tests.shared.paths import CasePaths


def folder(directory: str, files: int, subdirectories: int, *, inits: int = 0) -> inventory_code.FolderRecord:
    """One inventory row, shaped the way `repository_inventory` builds it."""
    return {
        "directory": directory,
        "files": files + inits,
        "rule_files": files,
        "subdirectories": subdirectories,
        "items": files + inits + subdirectories,
        "markdown_files": 0,
        "python_modules": 0,
    }


class FolderRuleTests(unittest.TestCase):
    def test_a_folder_holding_one_file_and_nothing_else_fails(self):
        ends = inventory_code.folder_validation([folder("scripts/tests/retired", 1, 0)])
        self.assertEqual([item["directory"] for item in ends.single], ["scripts/tests/retired"])

    def test_a_folder_that_groups_subdirectories_is_not_a_single_file_folder(self):
        ends = inventory_code.folder_validation(
            [folder(".agents/skills", 0, 4), folder("scripts/tests/cases", 1, 11), folder("cases/personal", 0, 1)]
        )
        self.assertEqual(ends.single, [])

    def test_the_skill_loader_lays_out_one_folder_per_skill(self):
        ends = inventory_code.folder_validation([folder(".agents/skills/docs-writing", 1, 0)])
        self.assertEqual(ends.single, [])

    def test_a_package_init_is_not_counted(self):
        ends = inventory_code.folder_validation([folder("scripts/launchers/asr/handy", 1, 0, inits=1)])
        self.assertEqual([item["directory"] for item in ends.single], ["scripts/launchers/asr/handy"])

    def test_two_to_three_files_stay_a_merge_candidate(self):
        ends = inventory_code.folder_validation([folder("scripts/config/models", 3, 0)])
        self.assertEqual([item["directory"] for item in ends.small], ["scripts/config/models"])
        self.assertEqual(ends.single, [])

    def test_more_than_twenty_files_fails(self):
        ends = inventory_code.folder_validation([folder("scripts/tests/cases/review", 21, 0)])
        self.assertEqual([item["directory"] for item in ends.crowded], ["scripts/tests/cases/review"])


class WorkspaceTotalTests(unittest.TestCase):
    def test_the_evidence_tree_is_subtracted_from_the_source_tree_it_sits_in(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder) / "workspace"
            (root / "scripts" / "state").mkdir(parents=True)
            (root / "scripts" / "our_module.py").write_text("x = 1\n", encoding="utf-8")
            (root / "scripts" / "state" / "run.log").write_text("log\n", encoding="utf-8")
            (root / "notes").mkdir()
            (root / "README.md").write_text("readme\n", encoding="utf-8")
            totals = inventory_code.workspace_totals(root)
            rows = {item.tree: item for item in totals}
            self.assertEqual(rows["scripts"].files, 1)
            self.assertEqual(rows["scripts"].kind, "our source")
            self.assertEqual(rows["scripts/state"].files, 1)
            self.assertEqual(rows["scripts/state"].kind, "run evidence")
            self.assertEqual(rows["(root files)"].files, 1)
            self.assertEqual(sum(item.files for item in totals), 3)

    def test_an_installed_tree_and_a_weight_tree_are_named_by_what_they_hold(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder) / "workspace"
            for name, payload in (("frameworks", "engine.exe"), ("data", "weights.gguf")):
                (root / name).mkdir(parents=True)
                (root / name / payload).write_bytes(b"x" * 10)
            rows = {item.tree: item for item in inventory_code.workspace_totals(root)}
            self.assertEqual((rows["frameworks"].kind, rows["frameworks"].bytes), ("installs", 10))
            self.assertEqual((rows["data"].kind, rows["data"].bytes), ("weights", 10))

    def test_the_report_shares_add_up_to_the_whole_folder(self):
        rows = [
            inventory_code.TreeTotal("frameworks", "installs", 75, 3 * 1024**3),
            inventory_code.TreeTotal("scripts", "our source", 25, 1024**3),
        ]
        text = "\n".join(inventory_code.workspace_report(rows, tracked=40))
        self.assertIn("| frameworks | installs | 75 | 75.0 | 3.00 | 75.0 |", text)
        self.assertIn("40 tracked files", text)


if __name__ == "__main__":
    unittest.main()
