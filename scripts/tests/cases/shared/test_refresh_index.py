"""The post-commit refresh rebuilds both indexes for code and leaves graphify alone for docs."""

import contextlib
import io
import unittest
from pathlib import Path

from scripts.tools import refresh_index
from scripts.tools.refresh_index import Step


def present(name: str) -> str:
    return f"C:/tools/{name}.exe"


class RefreshPlanTests(unittest.TestCase):
    def test_code_change_plans_both_indexes(self):
        steps = refresh_index.plan(["scripts/tools/refresh_index.py"], Path("C:/AI"), resolve=present)
        self.assertEqual([step.name for step in steps], ["codebase-memory", "graphify"])
        self.assertEqual(len(steps[1].commands), 2)
        self.assertEqual(steps[1].commands[1][1:3], ("cluster-only", "C:/AI"))
        self.assertEqual(steps[1].cwd, "C:/AI")

    def test_docs_only_change_skips_graphify(self):
        steps = refresh_index.plan([".agents/CODE-SEARCH.md", "notes/TODO.md"], Path("C:/AI"), resolve=present)
        self.assertEqual(steps[1].skip, "no extracted file in this commit")
        self.assertEqual(steps[1].commands, ())

    def test_unknown_change_set_refreshes_everything(self):
        self.assertTrue(refresh_index.needs_graphify([]))
        self.assertFalse(refresh_index.needs_graphify(["README.md"]))
        self.assertTrue(refresh_index.needs_graphify(["README.md", "scripts/tools/refresh_index.py"]))

    def test_missing_binaries_plan_no_command(self):
        steps = refresh_index.plan(["scripts/x.py"], Path("C:/AI"), resolve=lambda name: "")
        self.assertEqual([step.commands for step in steps], [(), ()])
        self.assertTrue(all(step.skip.endswith("not installed") for step in steps))


class RefreshReportTests(unittest.TestCase):
    def _line(self, *args) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            refresh_index.report(*args)
        return buffer.getvalue().strip()

    def test_success_reports_the_step_time(self):
        self.assertEqual(self._line(Step("graphify"), 18.2, 0, ""), "[OK] graphify 18.2 s")

    def test_failure_reports_the_indexer_exit_code_and_its_last_line(self):
        line = self._line(Step("graphify"), 3.0, 3, "fatal: bad graph")
        self.assertEqual(line, "[FAIL] graphify 3.0 s exit 3: fatal: bad graph")

    def test_windows_crash_status_keeps_its_meaning(self):
        line = self._line(Step("codebase-memory"), 1.0, 0xC0000005, "crashed")
        self.assertIn("0xC0000005 (3221225477, access violation)", line)

    def test_skip_names_the_reason(self):
        self.assertEqual(
            self._line(Step("graphify", skip="graphify not installed")), "[SKIP] graphify: graphify not installed"
        )
