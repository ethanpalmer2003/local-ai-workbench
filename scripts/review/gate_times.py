"""Typical gate section times: medians over the retained run logs, so no doc quotes a guess.

Each gate run writes its per-section seconds beside the report; the count column shows how many
runs each median rests on, since --fast runs skip the slow sections.
"""

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.shared.tables import render_table

LOG_DIR = project_cfg.BASE_DIR / "scripts" / "state" / "logs" / "shared" / "review"


@dataclass(frozen=True)
class SectionTime:
    section: str
    median_seconds: float
    runs: int


def summaries(logs_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every retained gate report that still parses; a partial write is skipped, not failed."""
    reports = []
    for path in sorted((logs_dir or LOG_DIR).glob("*.json")):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return reports


def medians(reports: list[dict[str, Any]]) -> list[SectionTime]:
    """One row per section plus the wall and work totals, slowest first."""
    by_section: dict[str, list[float]] = {}
    for report in reports:
        for entry in report.get("sections", []):
            by_section.setdefault(str(entry["section"]), []).append(float(entry["seconds"]))
    rows = [
        SectionTime(section, round(statistics.median(seconds), 2), len(seconds))
        for section, seconds in by_section.items()
    ]
    rows.sort(key=lambda row: row.median_seconds, reverse=True)
    for key in ("total_seconds", "work_seconds"):
        times = [float(report[key]) for report in reports if key in report]
        if times:
            rows.append(SectionTime(key, round(statistics.median(times), 2), len(times)))
    return rows


def report(logs_dir: Path | None = None) -> str:
    """The timing table, for the console or an answer."""
    return render_table(
        [[row.section, f"{row.median_seconds:.2f}", str(row.runs)] for row in medians(summaries(logs_dir))],
        ["section", "median_s", "runs"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable rows")
    args = parser.parse_args(argv)
    if args.json:
        print(json.dumps([row.__dict__ for row in medians(summaries())], indent=2))
        return 0
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
