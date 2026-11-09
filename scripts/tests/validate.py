"""Run the gate, the model-free suite and both live suites in one terminal with a single progress bar.

Live stages skip themselves when their sources and installations are unchanged, exactly as the suites
do on their own; pass `--force` or set `AI_LIVE_FORCE=1` to rerun them. A stage that ends above its
expected range is reported as slow. The ranges live in `scripts/tests/shared/stage_times.py`.
"""

import argparse
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tqdm import tqdm

from scripts.config import project_config as project_cfg
from scripts.tests.shared import stage_times

STEP_RE = re.compile(r"^=== (.+) ===$")
PROGRESS_RE = re.compile(r"^\[PROGRESS\] \S+ \[[#-]*\] (\d+)/(\d+)(?: (.*))?$")
SKIP_RE = re.compile(r"^\[SKIP\] (?:launchers|backends):")
SHOWN_RE = re.compile(r"^\[(?:OK|FAIL|WARN|ERROR|SKIP|TIME|START|RESULTS)\]")
BAR_FORMAT = "{desc:>9} {percentage:3.0f}%|{bar:28}| {n:.0f}/{total:.0f}s  {postfix}"


@dataclass(frozen=True)
class Stage:
    key: str
    module: str
    arguments: tuple[str, ...] = ()


STAGES = (
    Stage("gate", "scripts.review"),
    Stage("suite", "scripts.tests.run"),
    Stage("launchers", "scripts.tests.cases.shared.live_frameworks"),
    Stage("backends", "scripts.tests.cases.shared.quick_validation"),
)


@dataclass
class Result:
    key: str
    status: str
    seconds: float
    note: str = ""


@dataclass
class _Live:
    """What the running child has reported so far."""

    fraction: float = 0.0
    note: str = ""
    skipped: bool = False


def command(stage: Stage) -> list[str]:
    return [sys.executable, "-m", stage.module, *stage.arguments]


def plan(only: list[str] | None = None) -> tuple[Stage, ...]:
    """The stages for this run, in execution order; `only` narrows by key."""
    return tuple(stage for stage in STAGES if not only or stage.key in only)


def parse_progress(line: str) -> tuple[int, int, str] | None:
    """`[PROGRESS] launchers [###-] 3/6 sdcpp` -> (3, 6, 'sdcpp')."""
    match = PROGRESS_RE.match(line)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), (match.group(3) or "").strip()


def skipped(line: str) -> bool:
    return bool(SKIP_RE.match(line))


def _consume(line: str, live: _Live, bar: Any, stage_key: str) -> None:
    if skipped(line):
        live.skipped = True
        live.fraction = 1.0
        bar.write(line)
        return
    progress = parse_progress(line)
    if progress is not None:
        done, total, name = progress
        live.fraction = done / total
        live.note = f"{done}/{total} {name}".strip()
        return
    step = STEP_RE.match(line)
    if step and stage_key == "gate":
        live.note = step.group(1).strip().lower()
        return
    if SHOWN_RE.match(line):
        bar.write(line)


def _refresh(bar: Any, stage: Stage, prefix: float, weight: float, live: _Live, started: float) -> None:
    elapsed = time.perf_counter() - started
    fraction = max(live.fraction, elapsed / stage_times.typical(stage.key))
    slow = " SLOW" if elapsed > stage_times.high(stage.key) else ""
    bar.n = prefix + weight * min(fraction, 1.0)
    bar.set_description(stage.key)
    bar.set_postfix_str(f"{live.note} {elapsed:.0f}s{slow}".strip())
    bar.refresh()


def _reader(stream, lines: queue.Queue[str | None]) -> None:
    if stream is None:
        lines.put(None)
        return
    for row in stream:
        lines.put(row.rstrip("\r\n"))
    lines.put(None)


def _tail(path: Path, count: int = 12) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]
    except OSError:
        return []


def _run_stage(stage: Stage, log_path: Path, bar: Any, prefix: float, weight: float, verbose: bool) -> Result:
    started = time.perf_counter()
    live = _Live()
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command(stage),
            cwd=project_cfg.BASE_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=_reader, args=(process.stdout, lines), daemon=True).start()
        deadline: float | None = None
        while True:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                log.write(line + "\n")
                if verbose:
                    bar.write(line)
                else:
                    _consume(line, live, bar, stage.key)
            elif process.poll() is not None:
                # A surviving grandchild can hold the pipe open; stop once the output is drained.
                deadline = deadline or time.perf_counter() + 2.0
                if time.perf_counter() > deadline:
                    break
            _refresh(bar, stage, prefix, weight, live, started)
        seconds = time.perf_counter() - started
        code = process.wait()
    status = "skipped" if live.skipped and not code else ("failed" if code else "ok")
    if status == "failed":
        bar.write(f"[FAIL] {stage.key}: exit {code}; tail of {log_path.name}")
        for row in _tail(log_path):
            bar.write(f"  | {row}")
    return Result(stage.key, status, seconds, live.note)


def _describe(result: Result) -> str:
    low, _, high = stage_times.RANGES[result.key]
    if result.status == "skipped":
        return f"[SKIP] {result.key}: {result.seconds:.1f} s, unchanged since the last pass"
    if result.status == "failed":
        return f"[FAIL] {result.key}: {result.seconds:.1f} s (expected {low}-{high} s)"
    if stage_times.classify(result.key, result.seconds) == "slow":
        return f"[WARN] {result.key}: {result.seconds:.1f} s, above the expected {low}-{high} s"
    return f"[OK] {result.key}: {result.seconds:.1f} s (expected {low}-{high} s)"


def _mark(result: Result) -> str:
    if result.status == "skipped":
        return "SKIP"
    if result.status == "failed":
        return "FAIL"
    return "SLOW" if stage_times.classify(result.key, result.seconds) == "slow" else "OK"


def _summary(results: list[Result], total: float) -> None:
    print()
    print(f"{'stage':<10} {'result':<8} {'time':>9}  expected")
    for result in results:
        low, _, high = stage_times.RANGES[result.key]
        print(f"{result.key:<10} {_mark(result):<8} {result.seconds:>7.1f} s  {low}-{high} s")
    spent = sum(result.seconds for result in results)
    print(f"{'total':<10} {'':<8} {spent:>7.1f} s  planned about {total:.0f} s")


def _plan(stages: tuple[Stage, ...]) -> None:
    print("Full validation plan; live stages skip when unchanged:")
    for stage in stages:
        low, typical, high = stage_times.RANGES[stage.key]
        print(f"  {stage.key:<10} {typical:>4.0f} s typical, {low}-{high} s expected  {stage.module}")
    total = sum(stage_times.typical(stage.key) for stage in stages)
    print(f"  {'total':<10} {total:>4.0f} s when nothing is skipped")


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=[stage.key for stage in STAGES], help="run only these stages")
    parser.add_argument("--force", action="store_true", help="rerun live suites even when they are unchanged")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and expected ranges")
    parser.add_argument("--verbose", action="store_true", help="stream every child line instead of the tagged ones")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if args.force:
        os.environ["AI_LIVE_FORCE"] = "1"
    stages = plan(args.only)
    if args.dry_run:
        _plan(stages)
        return 0
    total = sum(stage_times.typical(stage.key) for stage in stages)
    log_dir = project_cfg.STATE_DIR / "shared" / "logs" / "validate" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    with tqdm(total=total, unit="s", ascii=True, desc="validate", bar_format=BAR_FORMAT) as bar:
        prefix = 0.0
        for stage in stages:
            weight = stage_times.typical(stage.key)
            result = _run_stage(stage, log_dir / f"{stage.key}.log", bar, prefix, weight, args.verbose)
            bar.write(_describe(result))
            results.append(result)
            prefix += weight
            bar.n = prefix
            bar.refresh()
    _summary(results, total)
    print(f"[LOG] {log_dir}")
    return 0 if all(result.status != "failed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
