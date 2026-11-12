"""Shared paths and evidence layout for benchmark runs."""

import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg

PERSONAL_AREAS = frozenset({"sdcpp", "comfyui"})


def grouped(relative: Path) -> Path:
    """Personal media/chat areas nest under personal/ so their evidence stays apart from core runs."""
    if relative.parts and relative.parts[0] in PERSONAL_AREAS:
        return Path("personal") / relative
    return relative


class Outcome(StrEnum):
    VERIFIED = "verified"
    NO_GAIN = "no-gain"
    INCONCLUSIVE = "inconclusive"
    SUPERSEDED = "superseded"
    UNREVIEWED = "unreviewed"


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def temp(self) -> Path:
        return self.root / "temp"

    def write_report(self, payload: dict[str, Any]) -> None:
        vram = (self.artifacts / "vram.json").exists()
        if vram:
            payload.setdefault("vram_file", "vram.json")
        if self.root.parent.name in Outcome:
            payload.setdefault("outcome", self.root.parent.name)
        seconds = payload.get("total_seconds")
        elapsed = (
            f"{seconds:.3f} seconds (including startup and cleanup)"
            if seconds is not None
            else "unknown (not recorded)"
        )
        # - default=str: a report may carry a Path from a caller's settings; the text is the record
        (self.artifacts / "report.json").write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        (self.artifacts / "report.md").write_text(
            f"# {payload['name']}\n\nCategory: {payload['category']}\n\nOutcome: {payload.get('outcome', 'unreviewed')}\n\n"
            f"Status: {payload['status']}\n\n"
            f"Reasoning: {payload.get('reasoning', 'unknown (not recorded)')}\n\n"
            f"Elapsed: {elapsed}.\n\n"
            "Detailed results and timings are in this artifacts folder; server/tool logs are in ../logs/.\n"
            + ("\n- [VRAM baseline, process usage and sampled peaks](vram.json).\n" if vram else ""),
            encoding="utf-8",
        )

    def create(self) -> None:
        for directory in (self.logs, self.artifacts, self.temp):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class BenchmarkPaths:
    source: str

    @property
    def root(self) -> Path:
        return project_cfg.SCRIPTS_DIR / "benchmarks"

    @property
    def relative_source(self) -> Path:
        return Path(self.source).resolve().relative_to(self.root)

    @property
    def output(self) -> Path:
        return self.root / "output" / grouped(self.relative_source).with_suffix("")

    def new_run(self, outcome: Outcome = Outcome.UNREVIEWED) -> RunPaths:
        relative = self.relative_source.with_suffix("")
        run = RunPaths(self.output / outcome / str(time.time_ns()))
        run.create()
        guide = run.root.parent / "README.md"
        if not guide.exists():
            guide.write_text(
                f"# {relative.stem}: {outcome}\n\nRuns in this folder have outcome `{outcome}`.\n\n"
                "Each run uses logs/, artifacts/, and temp/. Open artifacts/report.md for status and evidence.\n",
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
