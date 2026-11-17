"""The folder rule: one file and nothing else fails, a sparse folder is only a merge candidate."""

import unittest

from scripts.review.checks import inventory_code


def folder(directory: str, files: int, subdirectories: int) -> inventory_code.FolderRecord:
    """One inventory row, shaped the way `repository_inventory` builds it."""
    return {
        "directory": directory,
        "files": files,
        "subdirectories": subdirectories,
        "items": files + subdirectories,
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

    def test_two_to_three_files_stay_a_merge_candidate(self):
        ends = inventory_code.folder_validation([folder("scripts/config/models", 3, 0)])
        self.assertEqual([item["directory"] for item in ends.small], ["scripts/config/models"])
        self.assertEqual(ends.single, [])

    def test_more_than_twenty_files_fails(self):
        ends = inventory_code.folder_validation([folder("scripts/tests/cases/review", 21, 0)])
        self.assertEqual([item["directory"] for item in ends.crowded], ["scripts/tests/cases/review"])


if __name__ == "__main__":
    unittest.main()
