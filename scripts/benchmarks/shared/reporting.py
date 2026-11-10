"""Common per-run status and elapsed time, alongside each runner's detailed artifacts."""

import csv
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.benchmark import summarize_report
from scripts.benchmarks.shared.paths import RunPaths

BENCHMARK_REASONING_EFFORT = "low"


def write_results(output: RunPaths, rows: list[dict[str, Any]]) -> None:
    """Keep complete JSON and a flat CSV with one row per completed measurement."""
    (output.artifacts / "results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    def flatten(row: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        fields = {}
        for key, value in row.items():
            name = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                fields.update(flatten(value, name))
            else:
                fields[name] = json.dumps(value) if isinstance(value, (list, tuple)) else value
        return fields

    flattened = [flatten(row) for row in rows]
    columns = list(dict.fromkeys(key for row in flattened for key in row))
    with (output.artifacts / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(flattened)


@dataclass
class RunReport:
    name: str
    category: str
    reasoning: str = "not applicable"
    status: str = "running"
    total_seconds: float = 0
    started: float = field(default_factory=time.perf_counter, repr=False)
    settings: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def record_provenance(
        self, *, models: list[dict[str, Any]], frameworks: list[dict[str, Any]], corpus: dict[str, Any] | None = None
    ) -> None:
        """Stamp what this run used, so the capability matrix can judge it instead of guessing."""
        self.provenance = provenance.block(
            subject=self.name, config=self.settings, frameworks=frameworks, models=models, corpus=corpus
        )

    def save(self, output: RunPaths) -> None:
        self.total_seconds = round(time.perf_counter() - self.started, 3)
        payload = asdict(self)
        payload.pop("started")
        if not payload.get("provenance"):
            payload.pop("provenance", None)
        payload["total_seconds_scope"] = "whole_run_including_setup_warmup_and_cleanup"
        payload["resident_request_summary"] = summarize_report(self.results)
        output.write_report(payload)
        if self.results:
            write_results(output, self.results)


@contextmanager
def report_run(
    output: RunPaths,
    name: str,
    category: str,
    reasoning: str = "not applicable",
    *,
    settings: dict[str, Any] | None = None,
) -> Iterator[RunReport]:
    report = RunReport(name, category, reasoning=reasoning, settings=settings or {})
    report.save(output)
    try:
        yield report
    except BaseException as error:
        report.error = str(error)
        if isinstance(error, SystemExit) and error.code in (None, 0):
            report.status = "completed"
        else:
            report.status = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        raise
    else:
        if report.status == "running":
            report.status = "completed"
    finally:
        report.save(output)


def record_inputs(
    report: RunReport,
    *,
    frameworks: tuple[str, ...] = (),
    models: dict[str, str | Path] | None = None,
    corpus: dict[str, Any] | None = None,
) -> None:
    """Stamp a run with the frameworks it started and the model files it read.
    - a producer passes the component keys and paths it actually used; labels stay short
    """
    report.record_provenance(
        models=[provenance.file_identity(label, Path(path)) for label, path in (models or {}).items()],
        frameworks=[provenance.framework_state(key) for key in frameworks],
        corpus=corpus,
    )


def context_category(tokens: int) -> str:
    if tokens < 4096:
        return "low-context"
    if tokens < 32768:
        return "medium-context"
    return "high-context"
