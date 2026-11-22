"""Renaming a path repoints its references and reports the ones it could not reach."""

import contextlib
import io
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

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
        forms = dict(rename_path.reference_forms("notes/LABELS.md", "notes/GROUPINGS-INDEX.md"))
        self.assertEqual(forms["LABELS.md"], "GROUPINGS-INDEX.md")
        self.assertEqual(forms["notes/LABELS.md"], "notes/GROUPINGS-INDEX.md")

    def test_a_folder_move_stops_at_the_path(self):
        self.assertEqual(
            rename_path.reference_forms("scripts/config/shared", "scripts/config/common"),
            [
                ("scripts/config/shared", "scripts/config/common"),
                ("scripts\\config\\shared", "scripts\\config\\common"),
            ],
        )

    def test_a_python_module_also_renames_its_dotted_name(self):
        self.assertEqual(
            rename_path.dotted_forms("scripts/tests/scoping.py", "scripts/tests/selection.py"),
            [("scripts.tests.scoping", "scripts.tests.selection")],
        )

    def test_a_package_init_and_a_folder_have_no_dotted_form(self):
        self.assertEqual(rename_path.dotted_forms("scripts/tests/__init__.py", "scripts/tests/sub/__init__.py"), [])
        self.assertEqual(rename_path.dotted_forms("scripts/config/shared", "scripts/config/common"), [])

    def test_a_dotted_name_rewrites_only_as_a_whole_name(self):
        pairs = [rename_path.DottedPair("scripts.tools.x", "scripts.tools.y")]
        self.assertEqual(rename_path.rename_dotted("import scripts.tools.x\n", pairs), "import scripts.tools.y\n")
        # - a longer module that merely ends with the old name keeps its own prefix
        self.assertEqual(rename_path.rename_dotted("old_scripts.tools.x", pairs), "old_scripts.tools.x")


class ImportRewriteTests(unittest.TestCase):
    def test_a_module_imported_by_name_is_renamed_and_its_alias_kept(self):
        text = "from scripts.tests import scoping, other\nfrom scripts.tests import scoping as scope\n"
        rewritten = rename_path.rename_import_names(
            text, [rename_path.ImportRename("scripts.tests", "scoping", "selection")]
        )
        self.assertEqual(
            rewritten, "from scripts.tests import selection, other\nfrom scripts.tests import selection as scope\n"
        )

    def test_another_package_and_a_longer_name_are_untouched(self):
        text = "from scripts.other import scoping\nfrom scripts.tests import scoping_extras\n"
        self.assertEqual(
            rename_path.rename_import_names(text, [rename_path.ImportRename("scripts.tests", "scoping", "selection")]),
            text,
        )

    def test_a_dotted_name_sharing_the_prefix_is_not_truncated(self):
        text = "from scripts.tests.scoping_extras import helper\n"
        rewritten = rename_path.rename_dotted(
            text, [rename_path.DottedPair("scripts.tests.scoping", "scripts.tests.selection")]
        )
        self.assertEqual(rewritten, text)


class ReferenceRewriteTests(unittest.TestCase):
    def test_references_in_prose_code_and_batches_are_rewritten(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "notes").mkdir()
            (root / "notes" / "doc.md").write_text("See [labels](OLD-INDEX.md) and OLD-INDEX.md.\n", encoding="utf-8")
            (root / "script.py").write_text('PATH = "notes/OLD-INDEX.md"\n', encoding="utf-8")
            (root / "run.bat").write_text("python -m scripts.tools.yaml_table notes\\OLD-INDEX.md\n", encoding="utf-8")
            moves = {"notes/OLD-INDEX.md": "notes/NEW-INDEX.md"}
            changed = rename_path.rewrite_references(moves, dry_run=False, root=root)
            self.assertEqual(len(changed), 3)
            doc = (root / "notes" / "doc.md").read_text(encoding="utf-8")
            self.assertNotIn("OLD-INDEX", doc, "every spelling beside the moved file is repointed")
            self.assertIn("[labels](NEW-INDEX.md)", doc)
            self.assertIn("notes/NEW-INDEX.md", (root / "script.py").read_text(encoding="utf-8"))
            self.assertIn("notes\\NEW-INDEX.md", (root / "run.bat").read_text(encoding="utf-8"))

    def test_a_bare_basename_is_not_rewritten_outside_its_directory(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "suites").mkdir()
            (root / "suites" / "README.md").write_text("[smoke](frameworks_smoke.py)\n", encoding="utf-8")
            (root / "asr").mkdir()
            (root / "asr" / "smoke.py").write_text("X = 1\n", encoding="utf-8")
            rename_path.rewrite_references({"asr/smoke.py": "asr/parakeetcpp.py"}, dry_run=False, root=root)
            readme = (root / "suites" / "README.md").read_text(encoding="utf-8")
        self.assertIn("frameworks_smoke.py", readme, "a longer name sharing the basename is a different file")

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

    def test_both_import_spellings_of_a_moved_module_are_repointed(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "use.py").write_text(
                "from scripts.tests import scoping\nfrom scripts.tests.scoping import select\n", encoding="utf-8"
            )
            rename_path.rewrite_references(
                {"scripts/tests/scoping.py": "scripts/tests/selection.py"}, dry_run=False, root=root
            )
            text = (root / "use.py").read_text(encoding="utf-8")
        self.assertNotIn("scoping", text)
        self.assertIn("from scripts.tests import selection", text)
        self.assertIn("from scripts.tests.selection import select", text)

    def test_a_basename_the_tree_shares_is_never_rewritten_bare(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            for name in ("a", "b"):
                (root / name).mkdir()
                (root / name / "README.md").write_text(f"# {name}\n", encoding="utf-8")
            (root / "doc.md").write_text("See [a](a/README.md) and b/README.md.\n", encoding="utf-8")
            rename_path.rewrite_references({"a/README.md": "a/RETIRED.md"}, dry_run=False, root=root)
            doc = (root / "doc.md").read_text(encoding="utf-8")
        self.assertIn("[a](a/RETIRED.md)", doc)
        self.assertIn("b/README.md", doc)
        self.assertEqual(doc.count("RETIRED"), 1, "only the moved file's own path changes")


class PreviewTests(unittest.TestCase):
    def test_a_preview_counts_references_without_writing(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "a.md").write_text("notes/OLD.md and notes/OLD.md\n", encoding="utf-8")
            planned = rename_path.preview({"notes/OLD.md": "notes/NEW.md"}, root=root)
            self.assertEqual([(path.name, count) for path, count in planned], [("a.md", 2)])
            self.assertIn("OLD", (root / "a.md").read_text(encoding="utf-8"))

    def test_without_apply_main_reports_the_count_and_writes_nothing(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "a.md").write_text("notes/OLD.md\n", encoding="utf-8")
            printed = io.StringIO()
            with patch.object(rename_path, "ROOT", root), contextlib.redirect_stdout(printed):
                self.assertEqual(rename_path.main(["--move", "notes/OLD.md=notes/NEW.md"]), 0)
            self.assertIn("OLD", (root / "a.md").read_text(encoding="utf-8"))
        self.assertIn("[PREVIEW] 1 reference(s) in 1 file(s)", printed.getvalue())
        self.assertIn("[NEXT] re-run with --apply", printed.getvalue())


class CollapseTests(unittest.TestCase):
    def test_a_collapse_moves_the_module_and_repoints_both_import_spellings(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            package = root / "scripts" / "use"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text('"""One module."""\n', encoding="utf-8")
            (package / "impl.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "scripts" / "caller.py").write_text(
                "from scripts.use import impl\nfrom scripts.use.impl import VALUE\n", encoding="utf-8"
            )
            # - the model-free suite forbids a real process; git is never asked here
            with patch.object(
                rename_path.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="")
            ):
                rename_path.collapse("scripts/use", "scripts/use_impl.py", dry_run=False, root=root)
            self.assertFalse(package.exists())
            self.assertTrue((root / "scripts" / "use_impl.py").is_file())
            caller = (root / "scripts" / "caller.py").read_text(encoding="utf-8")
        self.assertIn("from scripts import use_impl", caller)
        self.assertIn("from scripts.use_impl import VALUE", caller)

    def test_an_init_that_holds_code_is_refused(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            package = root / "scripts" / "use"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
            (package / "impl.py").write_text("OTHER = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "merge it into the module"):
                rename_path.collapse_plan("scripts/use", "scripts/use.py", root=root)

    def test_a_package_with_a_subdirectory_is_refused(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            package = root / "scripts" / "use"
            (package / "child").mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "impl.py").write_text("VALUE = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "subdirectory"):
                rename_path.collapse_plan("scripts/use", "scripts/use.py", root=root)


class ScanScopeTests(unittest.TestCase):
    def test_the_scan_never_enters_a_workspace_tree(self):
        watched = {"data", "frameworks", "trash", "state", "output", ".venv"}
        scanned = [path.relative_to(rename_path.ROOT) for path in rename_path.text_files(rename_path.ROOT)]
        self.assertFalse(
            [str(path) for path in scanned if watched & set(path.parts)], "a workspace tree is never a source"
        )
        # - a whole-workspace walk is the way this tool goes from a fifth of a second to minutes
        self.assertLess(len(scanned), 10_000, "scan grew past the maintained source tree")


if __name__ == "__main__":
    unittest.main()
