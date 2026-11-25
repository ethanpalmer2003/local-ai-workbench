"""The post-commit refresh rebuilds the call graph now and hands the architecture graph to a background run."""

import contextlib
import io
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tools import refresh_index
from scripts.tools.refresh_index import Plan, Step


def present(name: str) -> str:
    return f"C:/tools/{name}.exe"


def code_plan() -> Plan:
    return Plan(Step("codebase-memory", (("cbm",),)), (("graphify",), ("graphify", "cluster-only")))


class RefreshPlanTests(unittest.TestCase):
    def test_code_change_plans_both_indexes(self):
        item = refresh_index.plan(["scripts/tools/refresh_index.py"], Path("C:/AI"), resolve=present)
        self.assertEqual(len(item.graphify), 3)
        self.assertEqual(item.graphify[1][1:3], ("cluster-only", "C:/AI"))
        self.assertEqual(item.graphify[2][1:4], ("export", "wiki", "--graph"))
        self.assertEqual(item.memory.cwd, "C:/AI")

    def test_docs_only_change_skips_graphify(self):
        item = refresh_index.plan([".agents/CODE-SEARCH.md", "notes/TODO.md"], Path("C:/AI"), resolve=present)
        self.assertEqual(item.graphify, ())
        self.assertEqual(item.graphify_skip, "no extracted file in this commit")

    def test_unknown_change_set_refreshes_everything(self):
        self.assertTrue(refresh_index.needs_graphify([]))
        self.assertFalse(refresh_index.needs_graphify(["README.md"]))
        self.assertTrue(refresh_index.needs_graphify(["README.md", "scripts/x.py"]))

    def test_missing_binaries_plan_no_command(self):
        item = refresh_index.plan(["scripts/x.py"], Path("C:/AI"), resolve=lambda name: "")
        self.assertEqual(item.memory.commands, ())
        self.assertTrue(item.memory.skip.endswith("not installed"))
        self.assertEqual(item.graphify_skip, "graphify not installed")


class RefreshLockTests(unittest.TestCase):
    def test_a_live_lock_is_respected_and_a_stale_one_is_taken(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "index-refresh.lock"
            self.assertTrue(refresh_index.acquire(lock))
            self.assertFalse(refresh_index.acquire(lock))
            old = time.time() - refresh_index.LOCK_STALE_SECONDS - 60
            os.utime(lock, (old, old))
            self.assertTrue(refresh_index.acquire(lock))

    def _run(self, lock: Path | None, code: int, output: str) -> tuple[str, int]:
        settled = subprocess.CompletedProcess(args=["graphify"], returncode=code, stdout=output, stderr="")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), patch.object(refresh_index.subprocess, "run", return_value=settled):
            result = refresh_index.run_graphify([["graphify", "update"]], Path("C:/AI"), lock)
        return buffer.getvalue(), result

    def test_the_background_run_reports_and_releases_the_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "index-refresh.lock"
            lock.touch()
            output, code = self._run(lock, 0, "done")
            self.assertEqual(code, 0)
            self.assertFalse(lock.exists())
            self.assertEqual(output.strip(), "[OK] graphify 0.0 s")

    def test_a_failed_background_run_reports_its_exit_code(self):
        output, code = self._run(None, 3, "")
        self.assertEqual(code, 3)
        self.assertIn("exit 3", output)


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
        line = self._line(Step("graphify", skip="graphify not installed"))
        self.assertEqual(line, "[SKIP] graphify: graphify not installed")


class RefreshBackgroundTests(unittest.TestCase):
    def _refresh(self, item: Plan, result: tuple[Step, float, int, str], **patched) -> tuple[str, int]:
        buffer = io.StringIO()
        with (
            contextlib.redirect_stdout(buffer),
            patch.multiple(refresh_index, plan=lambda paths, root: item, run_step=lambda step: result, **patched),
        ):
            code = refresh_index.refresh(["scripts/x.py"], Path("C:/AI"))
        return buffer.getvalue(), code

    def test_a_running_refresh_is_skipped_rather_than_duplicated(self):
        output, code = self._refresh(code_plan(), (Step("codebase-memory"), 2.0, 0, ""), acquire=lambda lock: False)
        self.assertEqual(code, 0)
        self.assertIn("[SKIP] graphify: a refresh is already running", output)

    def test_a_free_lock_starts_the_background_run(self):
        output, _ = self._refresh(
            code_plan(),
            (Step("codebase-memory"), 2.0, 0, ""),
            acquire=lambda lock: True,
            start_graphify=lambda root, lock: "C:/AI/index-refresh.log",
        )
        self.assertIn("[START] graphify in background: C:/AI/index-refresh.log", output)

    def test_a_failed_call_graph_still_fails_the_run(self):
        output, code = self._refresh(
            code_plan(),
            (Step("codebase-memory"), 2.0, 1, "boom"),
            acquire=lambda lock: True,
            start_graphify=lambda root, lock: "log",
        )
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] codebase-memory 2.0 s exit 1: boom", output)
