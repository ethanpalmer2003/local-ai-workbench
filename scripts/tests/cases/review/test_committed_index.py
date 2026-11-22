"""The committed index carries every import it names, and nothing an ignore rule covers."""

import ast
import subprocess
import unittest
from pathlib import Path

from scripts.review.checks import layout
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.paths import CasePaths


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)


class ResolveTests(unittest.TestCase):
    def test_a_module_file_a_package_and_a_namespace_package_all_resolve(self):
        indexed = frozenset({"scripts/a.py", "scripts/b/__init__.py", "scripts/c/mod.py"})
        self.assertTrue(layout.resolves_module("scripts.a", indexed))
        self.assertTrue(layout.resolves_module("scripts.b", indexed))
        self.assertTrue(layout.resolves_module("scripts.c", indexed))
        self.assertFalse(layout.resolves_module("scripts.missing", indexed))

    def test_only_absolute_scripts_imports_are_read(self):
        tree = ast.parse("import scripts.a as x\nfrom scripts.b.c import value\nfrom . import sibling\nimport os\n")
        self.assertEqual(layout.imported_modules(tree), {"scripts.a", "scripts.b.c"})


class IndexConsistencyTests(unittest.TestCase):
    @fixture_processes()
    def test_an_import_the_index_lacks_is_reported(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            _git(root, "init", "-q")
            (root / "a.py").write_text("from scripts.nothere import thing\n", encoding="utf-8")
            _git(root, "add", "a.py")
            issues = layout.index_issues(root)
        self.assertEqual(issues, ["a.py: imports scripts.nothere, which the index does not carry"])

    @fixture_processes()
    def test_an_import_the_index_carries_is_accepted(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            _git(root, "init", "-q")
            (root / "scripts").mkdir()
            (root / "scripts/__init__.py").write_text("", encoding="utf-8")
            (root / "a.py").write_text("from scripts import settings\n", encoding="utf-8")
            _git(root, "add", ".")
            issues = layout.index_issues(root)
        self.assertEqual(issues, [])

    @fixture_processes()
    def test_a_forced_file_under_an_ignored_path_is_reported(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            _git(root, "init", "-q")
            (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
            (root / "run.log").write_text("state\n", encoding="utf-8")
            _git(root, "add", ".gitignore")
            _git(root, "add", "-f", "run.log")
            issues = layout.index_issues(root)
        self.assertEqual(issues, ["run.log: indexed but matches an ignore rule; never force it in"])


if __name__ == "__main__":
    unittest.main()
