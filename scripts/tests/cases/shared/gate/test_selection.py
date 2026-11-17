"""Test selection: the suite runs the classes a change can reach, and every class when it cannot tell."""

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tests import selection
from scripts.tests.shared.paths import CasePaths


def _graph(edges: dict[str, tuple[str, ...]]) -> dict[str, frozenset[str]]:
    return {name: frozenset(targets) for name, targets in edges.items()}


class TestSelection(unittest.TestCase):
    def test_a_module_name_maps_files_and_packages(self):
        cases = (
            ("scripts/tools/model_admin.py", "scripts.tools.model_admin"),
            ("scripts/tools/__init__.py", "scripts.tools"),
            ("notes/TODO.md", None),
            ("README.md", None),
            ("scripts/state/logs/a.py", "scripts.state.logs.a"),
        )
        for path, expected in cases:
            self.assertEqual(selection.module_name(path), expected, path)

    def test_relative_imports_resolve_within_the_package(self):
        source = "from . import sibling\nfrom .sibling import thing\nfrom ..parent import other\n"
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = selection._target(node, "scripts.pkg.module", False)
                if base:
                    names.add(base)
                    names.update(f"{base}.{alias.name}" for alias in node.names)
        self.assertEqual(
            names,
            {
                "scripts.pkg",
                "scripts.pkg.sibling",
                "scripts.pkg.sibling.thing",
                "scripts.parent",
                "scripts.parent.other",
            },
        )

    def test_a_chain_of_importers_all_count(self):
        edges = _graph({"scripts.a": ("scripts.b",), "scripts.b": ("scripts.c",), "scripts.c": (), "scripts.z": ()})
        self.assertEqual(selection.dependencies(edges, "scripts.a"), {"scripts.a", "scripts.b", "scripts.c"})
        self.assertEqual(selection.affected(edges, {"scripts.c"}), {"scripts.c", "scripts.b", "scripts.a"})

    def test_an_unparsable_file_imports_nothing(self):
        with patch.object(Path, "read_text", side_effect=SyntaxError("bad")):
            self.assertEqual(selection.imported_names(Path("scripts/broken.py"), "scripts.broken"), set())

    def test_a_change_keeps_the_classes_that_import_it(self):
        from scripts.tests.cases.koboldcpp.test_kobold_options import KoboldOptionTests
        from scripts.tests.cases.review.test_docs import PointerTests

        edges = _graph(
            {
                "scripts.review.checks.docs": (),
                "scripts.launchers.koboldcpp.kobold": (),
                "scripts.tests.cases.review.test_docs": ("scripts.review.checks.docs",),
                "scripts.tests.cases.koboldcpp.test_kobold_options": ("scripts.launchers.koboldcpp.kobold",),
            }
        )
        groups = (PointerTests, KoboldOptionTests)
        with patch.object(selection, "graph", return_value=edges):
            chosen = selection.select(groups, paths=["scripts/review/checks/docs.py"])
        self.assertEqual(chosen.kept, (PointerTests,))
        self.assertEqual(chosen.dropped, (KoboldOptionTests,))

    def test_a_data_change_keeps_every_class(self):
        groups = (TestSelection,)
        for paths, why in (
            (["notes/TODO.md"], "not a Python module"),
            ([], "no change set"),
            (["scripts/tests/run.py"], "manifest changed"),
            (["scripts/tests/selection.py"], "manifest changed"),
        ):
            with self.subTest(paths=paths):
                chosen = selection.select(groups, paths=paths)
                self.assertEqual(chosen.kept, groups)
                self.assertIn(why, chosen.why)

    def test_all_keeps_every_class_whatever_changed(self):
        groups = (TestSelection,)
        with patch.object(selection, "changed_paths", return_value=["scripts/shared/wait.py"]):
            self.assertEqual(selection.select(groups, full=True).kept, groups)

    def test_every_class_is_kept_or_dropped_exactly_once(self):
        from scripts.tests.cases.koboldcpp.test_kobold_options import KoboldOptionTests
        from scripts.tests.cases.review.test_docs import PointerTests

        groups = (PointerTests, KoboldOptionTests)
        edges = _graph(
            {
                "scripts.review.checks.docs": (),
                "scripts.tests.cases.review.test_docs": ("scripts.review.checks.docs",),
                "scripts.tests.cases.koboldcpp.test_kobold_options": (),
            }
        )
        with patch.object(selection, "graph", return_value=edges):
            chosen = selection.select(groups, paths=["scripts/review/checks/docs.py"])
        self.assertEqual(
            sorted(group.__name__ for group in (*chosen.kept, *chosen.dropped)),
            sorted(group.__name__ for group in groups),
        )
        self.assertEqual(set(chosen.kept) & set(chosen.dropped), set())

    def test_a_dynamic_import_named_in_a_string_is_a_dependency(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "loader.py"
            path.write_text("import importlib\nimportlib.import_module('scripts.target')\n", encoding="utf-8")
            self.assertEqual(selection.literal_targets(path, {"scripts.loader", "scripts.target"}), {"scripts.target"})
            self.assertEqual(selection.literal_targets(path, {"scripts.loader"}), set())

    def test_a_module_git_has_not_seen_still_reaches_its_importers(self):
        from scripts.tests.cases.review.test_docs import PointerTests

        edges = _graph({"scripts.tests.cases.review.test_docs": ("scripts.review.checks.docs",)})
        with patch.object(selection, "graph", return_value=edges):
            chosen = selection.select((PointerTests,), paths=["scripts/review/checks/docs.py"])
        self.assertEqual(chosen.kept, (PointerTests,))

    def test_sources_reads_tracked_python_under_scripts(self):
        listing = "scripts/a.py\nscripts/b.md\nnotes/c.py\n"
        with patch.object(selection, "git", return_value=listing):
            self.assertEqual(selection.sources(), ["scripts/a.py"])

    def test_a_dropped_class_never_reaches_the_change(self):
        from scripts.tests.cases.koboldcpp.test_kobold_options import KoboldOptionTests
        from scripts.tests.cases.review.test_docs import PointerTests

        edges = _graph(
            {
                "scripts.review.checks.docs": (),
                "scripts.tests.cases.review.test_docs": ("scripts.review.checks.docs",),
                "scripts.tests.cases.koboldcpp.test_kobold_options": ("scripts.launchers.koboldcpp.kobold",),
            }
        )
        with patch.object(selection, "graph", return_value=edges):
            chosen = selection.select((PointerTests, KoboldOptionTests), paths=["scripts/review/checks/docs.py"])
        reach = selection.affected(edges, {"scripts.review.checks.docs"})
        for group in chosen.dropped:
            self.assertEqual(selection.dependencies(edges, group.__module__) & reach, set(), group.__name__)


if __name__ == "__main__":
    unittest.main()
