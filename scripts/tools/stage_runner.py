"""Run long stages one at a time behind a single progress bar.

Shared by the full validation runner and by any job that wants visible progress instead of a silent
wait: each stage is a module command with an expected duration, the bar is sized by those durations,
and a stage that ends above its high mark is reported as slow. Child output goes to a per-stage log;
tagged lines (`[OK]`, `[FAIL]`, `[SKIP]`, `[TIME]`, ...) are shown as they happen.
"""

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

STEP_RE = re.compile(r"^=== (.+) ===$")
PROGRESS_RE = re.compile(r"^\[PROGRESS\] \S+ \[[#-]*\] (\d+)/(\d+)(?: (.*))?$")
SKIP_RE = re.compile(r"^\[SKIP\] (\S+):")
SHOWN_RE = re.compile(r"^\[(?:OK|FAIL|WARN|ERROR|SKIP|TIME|START|RESULTS)\]")
BAR_FORMAT = "{desc:>12} {percentage:3.0f}%|{bar:26}| {n:.0f}/{total:.0f}s  {postfix}"


@dataclass(frozen=True)
class Stage:
    key: str
    module: str
    typical: float
    high: float
    arguments: tuple[str, ...] = ()


@dataclass
class Result:
    key: str
    status: str
    seconds: float
    note: str = ""
    log: Path | None = None


@dataclass
class _Live:
    """What the running child has reported so far."""

    fraction: float = 0.0
    note: str = ""
    skipped: bool = False


def command(stage: Stage) -> list[str]:
    return [sys.executable, "-m", stage.module, *stage.arguments]


def parse_progress(line: str) -> tuple[int, int, str] | None:
    """`[PROGRESS] launchers [###-] 3/6 sdcpp` -> (3, 6, 'sdcpp')."""
    match = PROGRESS_RE.match(line)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), (match.group(3) or "").strip()


def skipped(line: str) -> str | None:
    """The stage key on a whole-stage skip line, otherwise None."""
    match = SKIP_RE.match(line)
    return match.group(1) if match else None


def _consume(line: str, live: _Live, bar: Any, stage: Stage) -> None:
    key = skipped(line)
    if key == stage.key:
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
    if step:
        live.note = step.group(1).strip().lower()
        return
    if SHOWN_RE.match(line):
        bar.write(line)


def _refresh(bar: Any, stage: Stage, prefix: float, live: _Live, started: float) -> None:
    elapsed = time.perf_counter() - started
    fraction = max(live.fraction, elapsed / stage.typical)
    slow = " SLOW" if elapsed > stage.high else ""
    bar.n = prefix + stage.typical * min(fraction, 1.0)
    bar.set_description(stage.key)
    bar.set_postfix_str(f"{live.note} {elapsed:.0f}s{slow}".strip())
    bar.refresh()


def _reader(stream, lines: queue.Queue[str | None]) -> None:
    if stream is None:
        lines.put(None)
        return
    for row in stream:
        for part in row.replace("\r", "\n").splitlines():
            lines.put(part)
    lines.put(None)


def _tail(path: Path, count: int = 12) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]
    except OSError:
        return []


def _run_stage(stage: Stage, log_path: Path, bar: Any, prefix: float, verbose: bool) -> Result:
    started = time.perf_counter()
    live = _Live()
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "AI_TEST_TITLE": stage.key}
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
                    _consume(line, live, bar, stage)
            elif process.poll() is not None:
                # A surviving grandchild can hold the pipe open; stop once the output is drained.
                deadline = deadline or time.perf_counter() + 2.0
                if time.perf_counter() > deadline:
                    break
            _refresh(bar, stage, prefix, live, started)
        seconds = time.perf_counter() - started
        code = process.wait()
    status = "skipped" if live.skipped and not code else ("failed" if code else "ok")
    if status == "failed":
        bar.write(f"[FAIL] {stage.key}: exit {code}; tail of {log_path.name}")
        for row in _tail(log_path):
            bar.write(f"  | {row}")
    return Result(stage.key, status, seconds, live.note, log_path)


def _describe(result: Result, stage: Stage) -> str:
    if result.status == "skipped":
        return f"[SKIP] {stage.key}: {result.seconds:.1f} s, unchanged since the last pass"
    if result.status == "failed":
        return f"[FAIL] {stage.key}: {result.seconds:.1f} s (expected under {stage.high:.0f} s)"
    if stage.high and result.seconds > stage.high:
        return f"[WARN] {stage.key}: {result.seconds:.1f} s, above the expected {stage.high:.0f} s"
    return f"[OK] {stage.key}: {result.seconds:.1f} s"


def _mark(result: Result, stage: Stage) -> str:
    if result.status == "skipped":
        return "SKIP"
    if result.status == "failed":
        return "FAIL"
    return "SLOW" if stage.high and result.seconds > stage.high else "OK"


def summary(results: list[Result], stages: tuple[Stage, ...]) -> None:
    by_key = {stage.key: stage for stage in stages}
    print()
    print(f"{'stage':<12} {'result':<8} {'time':>9}  expected under")
    for result in results:
        stage = by_key[result.key]
        print(f"{result.key:<12} {_mark(result, stage):<8} {result.seconds:>7.1f} s  {stage.high:.0f} s")
    spent = sum(result.seconds for result in results)
    print(f"{'total':<12} {'':<8} {spent:>7.1f} s  planned about {sum(s.typical for s in stages):.0f} s")


def run(stages: tuple[Stage, ...], *, title: str = "stages", verbose: bool = False) -> list[Result]:
    """Run every stage in order behind one bar and print a per-stage summary."""
    if not stages:
        return []
    total = sum(stage.typical for stage in stages)
    log_dir = project_cfg.STATE_DIR / "shared" / "logs" / "runs" / title / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    with tqdm(total=total, unit="s", ascii=True, desc=title, bar_format=BAR_FORMAT) as bar:
        prefix = 0.0
        for stage in stages:
            result = _run_stage(stage, log_dir / f"{stage.key}.log", bar, prefix, verbose)
            bar.write(_describe(result, stage))
            results.append(result)
            prefix += stage.typical
            bar.n = prefix
            bar.refresh()
    summary(results, stages)
    print(f"[LOG] {log_dir}")
    return results
