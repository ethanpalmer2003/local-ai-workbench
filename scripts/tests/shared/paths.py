"""Test source/output mapping and temporary workspaces."""

import contextlib
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from scripts.benchmarks.shared.paths import Outcome, RunPaths, grouped
from scripts.config import project_config as project_cfg


@contextlib.contextmanager
def removed_on_exit(folder: Path) -> Iterator[str]:
    """Yield a scratch directory and delete it afterwards, failures included."""
    try:
        yield str(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@dataclass(frozen=True)
class CasePaths:
    source: str

    @property
    def relative_source(self) -> Path:
        return Path(self.source).resolve().relative_to(project_cfg.TEST_CASES_DIR)

    @property
    def output(self) -> Path:
        return project_cfg.TEST_OUTPUT_DIR / grouped(self.relative_source).with_suffix("")

    def new_run(self, outcome: Outcome = Outcome.UNREVIEWED) -> RunPaths:
        relative = self.relative_source.with_suffix("")
        run = RunPaths(self.output / outcome / str(time.time_ns()))
        run.create()
        guide = run.root.parent / "README.md"
        if not guide.exists():
            guide.write_text(
                f"# {relative.stem}: {outcome}\n\nRuns in this folder have outcome `{outcome}`.\n\n"
                "Each run uses logs/, artifacts/, and temp/. Open artifacts/report.md for status and recorded elapsed time; "
                "detailed evidence stays alongside it. Unknown timings and unreviewed status are not successful test results.\n",
                encoding="utf-8",
            )
        run.write_report(
            {
                "name": relative.as_posix(),
                "category": relative.parts[0],
                "status": "unreviewed",
                "total_seconds": None,
                "outcome": str(outcome),
            }
        )
        return run

    def temporary_directory(self) -> contextlib.AbstractContextManager[str]:
        # - tempfile.mkdtemp creates the directory with mode 0700, and on Windows that
        #   DACL excludes the restricted token a sandboxed run holds, so the test cannot
        #   write inside the directory it just made. A default-mode directory inherits
        #   the run's permissions and stays usable both confined and unconfined.
        folder = self.new_run().temp / f"tmp{time.time_ns()}"
        folder.mkdir(parents=True)
        return removed_on_exit(folder)
