"""Gate scoping: an empty change set runs every section, a change runs only what it reaches."""

import contextlib
import io
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import networkx


def _digraph(edges: dict[str, tuple[str, ...]]) -> networkx.DiGraph[str]:
    graph = networkx.DiGraph()
    graph.add_nodes_from(edges)
    graph.add_edges_from((name, target) for name, targets in edges.items() for target in targets)
    return graph


class GateScopeTests(unittest.TestCase):
    def test_a_batch_rename_only_needs_layout_and_docs(self):
        from scripts.review.__main__ import touched_sections

        self.assertEqual(touched_sections(["bat/checks/test_full.bat"]), {"layout", "docs", "single-owner tokens"})

    def test_a_python_edit_adds_the_code_sections(self):
        from scripts.review.__main__ import touched_sections

        sections = touched_sections(["scripts/tools/example.py"])
        self.assertTrue({"layout", "docs", "lint", "types", "dead code"} <= sections)
        self.assertNotIn("spelling", sections)

    def test_a_markdown_edit_adds_the_prose_sections_without_code_ones(self):
        from scripts.review.__main__ import touched_sections

        sections = touched_sections(["notes/TODO.md"])
        self.assertTrue({"docs", "typography", "spelling"} <= sections)
        self.assertNotIn("lint", sections)

    def test_git_output_is_decoded_as_text_whatever_the_console_codec(self):
        from scripts.shared import changes

        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"caf\x81 line\n", stderr=b"")
        with patch.object(changes.subprocess, "run", return_value=completed):
            self.assertEqual(changes.git_text("show", "scripts/a.py"), "caf\ufffd line\n")

    def test_the_change_set_covers_the_working_tree_and_unpushed_commits(self):
        from scripts.shared import changes

        def git_text(*args: str, **_: object) -> str:
            if args[0] == "status":
                return "R  bat/tests/a.bat -> bat/checks/a.bat\n M notes/TODO.md\n"
            return "scripts/tools/older.py\n"

        with patch.object(changes, "git_text", side_effect=git_text):
            self.assertEqual(
                changes.changed_since_upstream(),
                ["bat/checks/a.bat", "bat/tests/a.bat", "notes/TODO.md", "scripts/tools/older.py"],
            )

    def test_an_empty_change_set_checks_nothing(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_since_upstream", return_value=[]),
            patch.object(gate, "full_gate", return_value=0) as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            gate.main([])
        full.assert_not_called()
        touched.assert_not_called()

    def test_a_push_with_a_clean_tree_skips(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_since_upstream", return_value=[]),
            patch.object(gate, "full_gate") as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            self.assertEqual(gate.main(["--push"]), 0)
        full.assert_not_called()
        touched.assert_not_called()

    def test_a_branch_without_an_upstream_runs_everything(self):
        from scripts.review import __main__ as gate
        from scripts.shared.changes import NoUpstreamError

        buffer = io.StringIO()
        with (
            patch.object(gate, "changed_since_upstream", side_effect=NoUpstreamError),
            patch.object(gate, "full_gate", return_value=0) as full,
            contextlib.redirect_stdout(buffer),
        ):
            gate.main([])
        full.assert_called_once_with([])
        self.assertIn("no upstream ref", buffer.getvalue())

    def test_a_change_runs_only_the_touched_sections(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_since_upstream", return_value=["notes/TODO.md"]),
            patch.object(gate, "full_gate") as full,
            patch.object(gate, "touched_gate", return_value=0) as touched,
        ):
            gate.main([])
        touched.assert_called_once()
        full.assert_not_called()

    def test_a_commit_reads_the_working_tree_only(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_since_head", return_value=["scripts/shared/consent.py"]) as working,
            patch.object(gate, "changed_since_upstream") as upstream,
            patch.object(gate, "touched_gate", return_value=0) as touched,
            patch.object(gate, "full_gate"),
        ):
            self.assertEqual(gate.main(["--commit"]), 0)
        upstream.assert_not_called()
        working.assert_called_once_with()
        touched.assert_called_once_with([], ["scripts/shared/consent.py"])

    def test_the_uncommitted_change_set_ignores_unpushed_commits(self):
        from scripts.shared import changes

        calls: list[str] = []

        def git_text(*args: str, **_: object) -> str:
            calls.append(args[0])
            return " M notes/TODO.md\n"

        with patch.object(changes, "git_text", side_effect=git_text):
            self.assertEqual(changes.changed_since_head(), ["notes/TODO.md"])
        self.assertEqual(calls, ["status"])

    def test_all_runs_every_section_whatever_changed(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_since_upstream", return_value=["notes/TODO.md"]),
            patch.object(gate, "full_gate", return_value=0) as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            gate.main(["--all"])
        full.assert_called_once()
        touched.assert_not_called()

    def test_a_failing_run_names_the_sections_that_failed(self):
        from scripts.review import __main__ as gate

        saved = list(gate.TIMES)
        gate.TIMES[:] = [
            {"section": "types", "seconds": 11.0, "status": 1},
            {"section": "formatting", "seconds": 0.4, "status": 2},
            {"section": "lint", "seconds": 0.3, "status": 0},
        ]
        try:
            with redirect_stdout(StringIO()) as output:
                self.assertEqual(gate.report_sections(), 1)
        finally:
            gate.TIMES[:] = saved
        self.assertIn("[FAIL] 2 section(s) failed: types, formatting", output.getvalue())

    def test_a_passing_run_says_so(self):
        from scripts.review import __main__ as gate

        saved = list(gate.TIMES)
        gate.TIMES[:] = [{"section": "lint", "seconds": 0.3, "status": 0}]
        try:
            with redirect_stdout(StringIO()) as output:
                self.assertEqual(gate.report_sections(), 0)
        finally:
            gate.TIMES[:] = saved
        self.assertIn("[OK] every section passed", output.getvalue())

    def test_the_summary_names_each_section_its_verdict_and_the_totals(self):
        from scripts.review import __main__ as gate

        saved = list(gate.TIMES)
        gate.TIMES[:] = [
            {"section": "lint", "seconds": 0.2, "status": 0},
            {"section": "types", "seconds": 9.4, "status": 1},
        ]
        printed = {"lint": "All checks passed!\n[OK] Lint clean\n", "types": "c:/x.py:1: error\n[FAIL] 1 error\n"}
        try:
            with redirect_stdout(StringIO()) as output:
                gate.print_summary(printed)
        finally:
            gate.TIMES[:] = saved
        self.assertIn("Lint clean", output.getvalue())
        self.assertIn("FAIL", output.getvalue())
        self.assertIn("2 section(s)", output.getvalue())
        self.assertIn("1 failed", output.getvalue())

    def test_a_verdict_line_falls_back_to_the_last_line_it_has(self):
        from scripts.review import __main__ as gate

        self.assertEqual(gate.verdict_line("noise\n[OK] Layout: 3 files, 0 issues\n"), "Layout: 3 files, 0 issues")
        self.assertEqual(gate.verdict_line("first\nlast line\n"), "last line")
        self.assertEqual(gate.verdict_line(""), "")

    def test_scoped_types_check_only_the_change_and_its_importers(self):
        from scripts.review import __main__ as gate

        edges = _digraph({"scripts.a": (), "scripts.b": ("scripts.a",), "scripts.c": ("scripts.b",), "scripts.z": ()})
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with (
            patch.object(gate, "import_graph", return_value=edges),
            patch.object(gate, "git_module_files", return_value={name: Path(name) for name in edges}),
            patch.object(gate, "module_paths", side_effect=lambda modules: sorted(f"{name}.py" for name in modules)),
            patch.object(gate.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(gate.scoped_type_check(["scripts/a.py"], False), 0)
        self.assertEqual(sorted(run.call_args.args[0][3:]), ["scripts.a.py", "scripts.b.py"])

    def test_scoped_types_run_the_whole_project_when_the_reach_is_wide(self):
        from scripts.review import __main__ as gate

        edges = _digraph({"scripts.a": (), **{f"scripts.m{index}": ("scripts.a",) for index in range(5)}})
        with (
            patch.object(gate, "import_graph", return_value=edges),
            patch.object(gate, "git_module_files", return_value={name: Path(name) for name in edges}),
            patch.object(gate, "type_check", return_value=0) as full,
        ):
            self.assertEqual(gate.scoped_type_check(["scripts/a.py"], False), 0)
        full.assert_called_once_with(False)

    def test_a_section_reads_its_arguments_or_the_whole_tree(self):
        from scripts.config import project_config as project_cfg
        from scripts.review.lists import sources

        with patch.object(sources, "maintained_files", return_value=[Path("scripts/tests/a.py")]):
            self.assertEqual(sources.check_targets([], (".py",)), [Path("scripts/tests/a.py")])
        self.assertEqual(sources.check_targets(["notes/TODO.md"], (".py",)), [project_cfg.BASE_DIR / "notes/TODO.md"])

    def test_a_prose_only_push_runs_the_touched_sections(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_since_upstream", return_value=["notes/TODO.md"]),
            patch.object(gate, "touched_gate", return_value=0) as touched,
            patch.object(gate, "full_gate") as full,
        ):
            self.assertEqual(gate.main(["--push"]), 0)
        touched.assert_called_once_with([], ["notes/TODO.md"])
        full.assert_not_called()

    def test_a_push_with_python_runs_every_section(self):
        from scripts.review import __main__ as gate

        with (
            patch.object(gate, "changed_since_upstream", return_value=["scripts/shared/consent.py"]),
            patch.object(gate, "touched_gate") as touched,
            patch.object(gate, "full_gate", return_value=0) as full,
        ):
            self.assertEqual(gate.main(["--push"]), 0)
        full.assert_called_once_with([])
        touched.assert_not_called()

    def test_formatting_targets_the_change_and_drops_a_deleted_file(self):
        from scripts.review import format_py

        live = "scripts/review/format_py.py"
        with patch.object(format_py, "changed_since_upstream", return_value=["notes/TODO.md", live]):
            self.assertEqual(format_py.python_targets(False), [live])
        with patch.object(format_py, "changed_since_upstream", return_value=["scripts/gone.py"]):
            self.assertEqual(format_py.python_targets(False), ["."])
        with patch.object(format_py, "changed_since_upstream", return_value=["notes/TODO.md"]):
            self.assertEqual(format_py.python_targets(False), ["."])
        self.assertEqual(format_py.python_targets(True), ["."])


if __name__ == "__main__":
    unittest.main()
