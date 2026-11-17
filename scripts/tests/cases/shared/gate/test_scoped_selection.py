"""Test selection: the suite runs the classes a change can reach, and every class when it cannot tell."""

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.shared import import_graph as graph_api
from scripts.tests import scoped_selection
from scripts.tests.shared.paths import CasePaths


def _graph(edges: dict[str, tuple[str, ...]]) -> graph_api.Graph:
    return {name: frozenset(targets) for name, targets in edges.items()}


class TestSelection(unittest.TestCase):
    def test_a_module_name_maps_files_and_packages(self):
        cases = (
            ("scripts/tools/model_admin.py", "scripts.tools.model_admin"),
            ("scripts/tools/__init__.py", "scripts.tools"),
            ("notes/TODO.md", None),
            ("README.md", None),
            ("scripts/state/logs/a.py", "scripts.state.logs.a"),
            # - a data or template file under scripts/ is not a module, so it is an unmodelled path
            ("scripts/config/models/catalog.json", None),
            ("scripts/benchmarks/README.md", None),
            ("scripts/config/llamacpp/chat_template.jinja", None),
        )
        for path, expected in cases:
            self.assertEqual(graph_api.module_name(path), expected, path)

    def test_relative_imports_resolve_within_the_package(self):
        source = "from . import sibling\nfrom .sibling import thing\nfrom ..parent import other\n"
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = graph_api._from_import_target(node, "scripts.pkg.module", False)
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

    def test_a_relative_import_beyond_the_top_package_names_nothing(self):
        tree = ast.parse("from ..outside import thing\n")
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
        self.assertIsNone(graph_api._from_import_target(node, "scripts.pkg", False))

    def test_a_submodule_depends_on_the_known_parent_packages(self):
        listing = "scripts/__init__.py\nscripts/pkg/__init__.py\nscripts/pkg/module.py\n"
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            for relative in ("scripts/__init__.py", "scripts/pkg/__init__.py", "scripts/pkg/module.py"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            with patch.object(graph_api, "git", return_value=listing):
                edges = graph_api.import_graph(root)
        # - `scripts/__init__.py` names no module, so `scripts` itself never becomes a parent package
        self.assertEqual(edges["scripts.pkg.module"], frozenset({"scripts.pkg"}))

    def test_an_unparsable_file_has_no_tree(self):
        with CasePaths(__file__).temporary_directory() as folder:
            broken = Path(folder) / "broken.py"
            broken.write_text("def broken(:\n", encoding="utf-8")
            self.assertIsNone(graph_api.parse_source(broken))

    def test_a_chain_of_importers_counts_one_hop_by_default(self):
        edges = _graph({"scripts.a": ("scripts.b",), "scripts.b": ("scripts.c",), "scripts.c": (), "scripts.z": ()})
        self.assertEqual(
            graph_api.reverse_closure(edges, {"scripts.c"}, depth=scoped_selection.SCOPE_DEPTH),
            {"scripts.c", "scripts.b"},
        )
        self.assertEqual(graph_api.reverse_closure(edges, {"scripts.c"}), {"scripts.c", "scripts.b", "scripts.a"})

    def test_a_transitive_dependent_is_out_of_scope(self):
        from scripts.tests.cases.review.test_docs import PointerTests

        edges = _graph(
            {
                "scripts.review.checks.docs": (),
                "scripts.review.checks.links": ("scripts.review.checks.docs",),
                "scripts.tests.cases.review.test_docs": ("scripts.review.checks.links",),
            }
        )
        with (
            patch.object(scoped_selection, "cosmetic_only", return_value=False),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            chosen = scoped_selection.select((PointerTests,), paths=["scripts/review/checks/docs.py"])
        self.assertEqual(chosen.kept, (), "a two-hop dependent waits for the full run")

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
        with (
            patch.object(scoped_selection, "cosmetic_only", return_value=False),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            chosen = scoped_selection.select(groups, paths=["scripts/review/checks/docs.py"])
        self.assertEqual(chosen.kept, (PointerTests,))
        self.assertEqual(chosen.dropped, (KoboldOptionTests,))

    def test_the_launcher_block_is_in_the_graph_like_any_other_class(self):
        from scripts.tests.cases.suites.frameworks_smoke import DEFAULT_GROUPS, ProxyHTTP

        edges = _graph(
            {
                "scripts.launchers.audiocpp.audiocpp_proxy": (),
                "scripts.tests.cases.suites.frameworks_smoke_proxy": ("scripts.launchers.audiocpp.audiocpp_proxy",),
            }
        )
        with (
            patch.object(scoped_selection, "cosmetic_only", return_value=False),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            kept = scoped_selection.select(DEFAULT_GROUPS, paths=["scripts/launchers/audiocpp/audiocpp_proxy.py"])
            dropped = scoped_selection.select(DEFAULT_GROUPS, paths=["scripts/tools/rename_path.py"])
        self.assertEqual(kept.kept, (ProxyHTTP,), "a proxy change keeps the loopback tests that drive it")
        self.assertEqual(dropped.kept, (), "nothing outside the launcher wiring keeps the block")

    def test_a_non_python_change_runs_no_class(self):
        groups = (TestSelection,)
        for paths in (
            ["notes/TODO.md"],
            ["scripts/config/models/catalog.json"],
            ["scripts/benchmarks/README.md"],
            ["bat/checks/test_all.bat"],
        ):
            with self.subTest(paths=paths):
                chosen = scoped_selection.select(groups, paths=paths)
                self.assertEqual(chosen.kept, ())
                self.assertEqual(chosen.dropped, groups)
                self.assertEqual(chosen.why, "no Python change")

    def test_the_manifests_keep_every_class(self):
        groups = (TestSelection,)
        for path in ("scripts/tests/run.py", "scripts/tests/scoped_selection.py"):
            with self.subTest(path=path), patch.object(scoped_selection, "cosmetic_only", return_value=False):
                chosen = scoped_selection.select(groups, paths=[path])
                self.assertEqual(chosen.kept, groups)
                self.assertIn("manifest changed", chosen.why)

    def test_a_lock_config_or_package_init_runs_no_class(self):
        for path in ("pyproject.toml", "uv.lock", "scripts/__init__.py"):
            # - the package init is a code change here, so the reason is the missing module, not prose
            with self.subTest(path=path), patch.object(scoped_selection, "cosmetic_only", return_value=False):
                chosen = scoped_selection.select((TestSelection,), paths=[path])
                self.assertEqual(chosen.kept, ())
                self.assertEqual(chosen.why, "no Python change")

    def test_a_comment_edit_to_a_trigger_runs_nothing(self):
        with patch.object(scoped_selection, "cosmetic_only", return_value=True):
            chosen = scoped_selection.select((TestSelection,), paths=["scripts/tests/scoped_selection.py"])
        self.assertEqual(chosen.kept, ())
        self.assertEqual(chosen.why, "comment or docstring only")

    def test_a_comment_edit_to_an_ordinary_module_runs_nothing(self):
        with patch.object(scoped_selection, "cosmetic_only", return_value=True):
            chosen = scoped_selection.select((TestSelection,), paths=["scripts/shared/consent.py"])
        self.assertEqual(chosen.kept, ())
        self.assertEqual(chosen.why, "comment or docstring only")

    def test_a_cosmetic_module_beside_a_document_runs_nothing(self):
        with patch.object(scoped_selection, "cosmetic_only", return_value=True):
            chosen = scoped_selection.select((TestSelection,), paths=["scripts/shared/consent.py", "notes/TODO.md"])
        self.assertEqual(chosen.kept, ())
        self.assertEqual(chosen.why, "no Python change")

    def test_a_docstring_only_trigger_beside_code_still_scopes(self):
        from scripts.tests.cases.review.test_docs import PointerTests

        edges = _graph(
            {"scripts.review.checks.docs": (), "scripts.tests.cases.review.test_docs": ("scripts.review.checks.docs",)}
        )
        with (
            patch.object(
                scoped_selection, "cosmetic_only", side_effect=lambda path, *_: path in scoped_selection.FULL_TRIGGERS
            ),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            chosen = scoped_selection.select(
                (PointerTests,), paths=["scripts/tests/run.py", "scripts/review/checks/docs.py"]
            )
        self.assertEqual(chosen.kept, (PointerTests,))
        self.assertEqual(chosen.why, "2 of 2 modules reachable")

    def test_a_docstring_or_comment_edit_compares_equal(self):
        before = ast.parse('"""Old."""\n\n\ndef run() -> None:\n    """Doc."""\n    print(1)\n')
        after = ast.parse('"""New."""\n\n\n# a comment\ndef run() -> None:\n    """Other."""\n    print(1)\n')
        changed = ast.parse('"""New."""\n\n\ndef run() -> None:\n    """Other."""\n    print(2)\n')
        self.assertEqual(scoped_selection._without_docstrings(before), scoped_selection._without_docstrings(after))
        self.assertNotEqual(scoped_selection._without_docstrings(before), scoped_selection._without_docstrings(changed))

    def test_a_cosmetic_change_is_read_from_upstream(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            target = root / "scripts" / "run.py"
            target.write_text('"""New docstring."""\nVALUE = 1\n', encoding="utf-8")
            with patch.object(scoped_selection, "git", return_value='"""Old docstring."""\nVALUE = 1\n'):
                self.assertTrue(scoped_selection.cosmetic_only("scripts/run.py", root))
            target.write_text('"""New docstring."""\nVALUE = 2\n', encoding="utf-8")
            with patch.object(scoped_selection, "git", return_value='"""Old docstring."""\nVALUE = 1\n'):
                self.assertFalse(scoped_selection.cosmetic_only("scripts/run.py", root))

    def test_a_python_change_beside_a_document_still_scopes(self):
        from scripts.tests.cases.koboldcpp.test_kobold_options import KoboldOptionTests
        from scripts.tests.cases.review.test_docs import PointerTests

        edges = _graph(
            {
                "scripts.review.checks.docs": (),
                "scripts.tests.cases.review.test_docs": ("scripts.review.checks.docs",),
                "scripts.tests.cases.koboldcpp.test_kobold_options": (),
            }
        )
        groups = (PointerTests, KoboldOptionTests)
        with (
            patch.object(scoped_selection, "cosmetic_only", return_value=False),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            chosen = scoped_selection.select(groups, paths=["scripts/review/checks/docs.py", "notes/TODO.md"])
        self.assertEqual(chosen.kept, (PointerTests,))
        self.assertEqual(chosen.dropped, (KoboldOptionTests,))

    def test_an_empty_change_set_runs_every_class(self):
        chosen = scoped_selection.select((TestSelection,), paths=[])
        self.assertEqual(chosen.kept, (TestSelection,))
        self.assertEqual(chosen.why, "no change set")

    def test_all_keeps_every_class_and_never_asks_git(self):
        groups = (TestSelection,)
        with patch.object(scoped_selection, "changed_paths", side_effect=AssertionError("git was asked")):
            self.assertEqual(scoped_selection.select(groups, full=True).kept, groups)
            self.assertEqual(scoped_selection.select(groups, full=True).why, "--all")

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
        with (
            patch.object(scoped_selection, "cosmetic_only", return_value=False),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            chosen = scoped_selection.select(groups, paths=["scripts/review/checks/docs.py"])
        self.assertEqual(
            sorted(group.__name__ for group in (*chosen.kept, *chosen.dropped)),
            sorted(group.__name__ for group in groups),
        )
        self.assertEqual(set(chosen.kept) & set(chosen.dropped), set())

    def test_a_module_git_has_not_seen_still_reaches_its_importers(self):
        from scripts.tests.cases.review.test_docs import PointerTests

        edges = _graph({"scripts.tests.cases.review.test_docs": ("scripts.review.checks.docs",)})
        with (
            patch.object(scoped_selection, "cosmetic_only", return_value=False),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            chosen = scoped_selection.select((PointerTests,), paths=["scripts/review/checks/docs.py"])
        self.assertEqual(chosen.kept, (PointerTests,))

    def test_module_files_list_tracked_and_untracked_python_under_scripts(self):
        listing = "scripts/a.py\nscripts/b.md\nnotes/c.py\n"
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            (root / "scripts" / "a.py").write_text("", encoding="utf-8")
            with patch.object(graph_api, "git", return_value=listing) as run:
                self.assertEqual(graph_api.module_files(root), {"scripts.a": root / "scripts" / "a.py"})
        run.assert_called_once_with("ls-files", "--cached", "--others", "--exclude-standard", "scripts", root=root)

    def test_the_graph_is_built_from_the_root_it_was_given(self):
        with patch.object(graph_api, "git", return_value="") as run:
            self.assertEqual(graph_api.module_files(Path("elsewhere")), {})
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["root"], Path("elsewhere"))

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
        with (
            patch.object(scoped_selection, "cosmetic_only", return_value=False),
            patch.object(scoped_selection, "import_graph", return_value=edges),
        ):
            chosen = scoped_selection.select((PointerTests, KoboldOptionTests), paths=["scripts/review/checks/docs.py"])
        reach = graph_api.reverse_closure(edges, {"scripts.review.checks.docs"}, depth=scoped_selection.SCOPE_DEPTH)
        for group in chosen.dropped:
            self.assertNotIn(group.__module__, reach, group.__name__)


if __name__ == "__main__":
    unittest.main()
