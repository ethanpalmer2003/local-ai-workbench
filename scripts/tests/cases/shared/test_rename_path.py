"""Renaming a path repoints its references and reports the ones it could not reach."""

import unittest
from pathlib import Path

from scripts.tests.shared.paths import CasePaths
from scripts.tools import rename_path


class MoveParsingTests(unittest.TestCase):
    def test_a_move_pairs_two_repo_relative_paths(self):
        self.assertEqual(rename_path.parse_moves(["notes/OLD.md=notes/NEW.md"]), {"notes/OLD.md": "notes/NEW.md"})

    def test_a_move_cannot_escape_the_workspace(self):
        for value in ("../outside.md=notes/NEW.md", "notes/OLD.md=C:/AI/elsewhere.md"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "inside the workspace"):
                rename_path.parse_moves([value])

    def test_conflicting_targets_for_one_source_are_refused(self):
        with self.assertRaisesRegex(ValueError, "Conflicting mappings"):
            rename_path.parse_moves(["notes/OLD.md=notes/A.md", "notes/OLD.md=notes/B.md"])

    def test_a_file_keeps_its_basename_and_path_spellings(self):
        forms = dict(rename_path.reference_forms("notes/LABELS.md", "notes/LABELS-INDEX.md"))
        self.assertEqual(forms["LABELS.md"], "LABELS-INDEX.md")
        self.assertEqual(forms["notes/LABELS.md"], "notes/LABELS-INDEX.md")

    def test_a_folder_move_stops_at_the_path(self):
        self.assertEqual(
            rename_path.reference_forms("scripts/config/shared", "scripts/config/common"),
            [
                ("scripts/config/shared", "scripts/config/common"),
                ("scripts\\config\\shared", "scripts\\config\\common"),
            ],
        )


class ReferenceRewriteTests(unittest.TestCase):
    def test_references_in_prose_code_and_batches_are_rewritten(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "doc.md").write_text("See [labels](OLD-INDEX.md) and notes/OLD-INDEX.md.\n", encoding="utf-8")
            (root / "script.py").write_text('PATH = "notes/OLD-INDEX.md"\n', encoding="utf-8")
            (root / "run.bat").write_text("python -m scripts.tools.yaml_table notes\\OLD-INDEX.md\n", encoding="utf-8")
            moves = {"notes/OLD-INDEX.md": "notes/NEW-INDEX.md"}
            changed = rename_path.rewrite_references(moves, dry_run=False, root=root)
            self.assertEqual(len(changed), 3)
            doc = (root / "doc.md").read_text(encoding="utf-8")
            self.assertNotIn("OLD-INDEX", doc, "every spelling should be repointed")
            self.assertIn("[labels](NEW-INDEX.md)", doc)
            self.assertIn("notes/NEW-INDEX.md", doc)
            self.assertIn("notes\\NEW-INDEX.md", (root / "run.bat").read_text(encoding="utf-8"))

    def test_a_dry_run_reports_without_writing(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            target = root / "doc.md"
            target.write_text("notes/OLD-INDEX.md\n", encoding="utf-8")
            changed = rename_path.rewrite_references(
                {"notes/OLD-INDEX.md": "notes/NEW-INDEX.md"}, dry_run=True, root=root
            )
            self.assertEqual(len(changed), 1)
            self.assertIn("OLD-INDEX", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
