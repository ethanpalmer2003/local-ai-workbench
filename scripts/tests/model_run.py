"""Run one long model test under a dry run, a silence watchdog and a wall-clock cap.

The quick check (default) proves the inputs exist, the ports are free and the module imports, then
prints the exact command without loading a model. The run itself kills the whole process tree when
the child stops printing and stops burning CPU (a frozen server) or when the wall-clock cap ends.
"""

import argparse
import importlib
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util

DEFAULT_SILENCE = 180.0
DEFAULT_MINUTES = 20.0
POLL = 1.0
TAIL = 15


@dataclass(frozen=True)
class RunSpec:
    label: str
    module: str
    arguments: tuple[str, ...]
    minutes: float
    silence: float
    requires: tuple[Path, ...] = ()
    ports: tuple[int, ...] = ()


def _missing(requires: tuple[Path, ...]) -> list[str]:
    return [str(path) for path in requires if not path.is_file()]


def _busy(ports: tuple[int, ...]) -> list[int]:
    return [port for port in ports if launch_util.port_listening(port)]


def check(spec: RunSpec) -> list[str]:
    """Problems that would waste a long run; an empty list means the dry run passes."""
    problems = [f"missing input: {path}" for path in _missing(spec.requires)]
    problems.extend(f"port {port} is already in use" for port in _busy(spec.ports))
    try:
        importlib.import_module(spec.module)
    except ImportError as error:
        problems.append(f"cannot import {spec.module}: {error}")
    return problems


def command(spec: RunSpec) -> list[str]:
    return [sys.executable, "-m", spec.module, *spec.arguments]


def describe(spec: RunSpec) -> None:
    print(f"[DRY RUN] {spec.label}")
    print(f"  module : {spec.module} {' '.join(spec.arguments)}".rstrip())
    print(f"  limits : {spec.minutes:.0f} min wall clock, {spec.silence:.0f} s silence")
    if spec.requires:
        print(f"  inputs : {', '.join(str(path) for path in spec.requires)}")
    if spec.ports:
        print(f"  ports  : {', '.join(map(str, spec.ports))}")
    print(f"  command: {' '.join(command(spec))}")


def _cpu_seconds(process: subprocess.Popen[bytes]) -> float | None:
    try:
        times = psutil.Process(process.pid).cpu_times()
    except psutil.Error:
        return None
    return times.user + times.system


def _tail(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL:]
    except OSError:
        return []


def _watch(process: subprocess.Popen[bytes], log_path: Path, spec: RunSpec, failure: dict[str, str]) -> None:
    """Kill an owned process tree that stopped printing and stopped using CPU, or outlived its cap."""
    started = time.monotonic()
    size, cpu = log_path.stat().st_size if log_path.exists() else 0, _cpu_seconds(process)
    moved = started
    while process.poll() is None:
        time.sleep(POLL)
        now = time.monotonic()
        current = log_path.stat().st_size if log_path.exists() else 0
        current_cpu = _cpu_seconds(process)
        if current != size or (current_cpu is not None and cpu is not None and current_cpu > cpu + 0.5):
            size, cpu, moved = current, current_cpu, now
        if now - started > spec.minutes * 60:
            failure["reason"] = f"wall clock cap {spec.minutes:.0f} min reached"
        elif now - moved > spec.silence:
            failure["reason"] = f"no output and no CPU for {spec.silence:.0f} s"
        if failure:
            launch_util.kill_process_tree(process.pid)
            return


def run(spec: RunSpec) -> int:
    problems = check(spec)
    if problems:
        print("[FAIL] dry run failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 2
    log_dir = project_cfg.STATE_DIR / "logs" / "model_runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{spec.module.rsplit('.', 1)[-1]}.log"
    print(f"[RUN] {spec.label}: {' '.join(command(spec))}", flush=True)
    print(f"[LOG] {log_path}", flush=True)
    failure: dict[str, str] = {}
    with log_path.open("wb") as log:
        process = subprocess.Popen(command(spec), cwd=project_cfg.BASE_DIR, stdout=log, stderr=subprocess.STDOUT)
        launch_util.assign_process_to_job(process.pid)
        watcher = threading.Thread(target=_watch, args=(process, log_path, spec, failure), daemon=True)
        watcher.start()
        try:
            code = process.wait()
        finally:
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
                process.wait(timeout=30)
    if failure:
        print(f"[FAIL] {spec.label}: {failure['reason']}; tail of {log_path}")
        for row in _tail(log_path):
            print(f"  | {row}")
        return 1
    if code:
        print(f"[FAIL] {spec.label}: exit {code}; tail of {log_path}")
        for row in _tail(log_path):
            print(f"  | {row}")
        return code
    print(f"[OK] {spec.label}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "module", nargs="?", help="module to run, for example scripts.benchmarks.llamacpp.benchmark_specspeed"
    )
    parser.add_argument("--label", default="model run")
    parser.add_argument(
        "--dry-run", action="store_true", help="check inputs and ports, print the command, load nothing"
    )
    parser.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    parser.add_argument("--silence", type=float, default=DEFAULT_SILENCE)
    parser.add_argument("--require", action="append", default=[], type=Path, help="input file that must exist")
    parser.add_argument("--port", action="append", default=[], type=int, help="port that must be free")
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="-- then the module's own arguments")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.module:
        print("[FAIL] a module is required")
        return 2
    rest = list(args.arguments)
    if rest[:1] == ["--"]:
        rest = rest[1:]
    spec = RunSpec(
        label=args.label,
        module=args.module,
        arguments=tuple(rest),
        minutes=args.minutes,
        silence=args.silence,
        requires=tuple(args.require),
        ports=tuple(args.port),
    )
    if args.dry_run:
        describe(spec)
        problems = check(spec)
        for problem in problems:
            print(f"  - [FAIL] {problem}")
        print("[OK] dry run passed" if not problems else "[FAIL] dry run failed")
        return 0 if not problems else 2
    return run(spec)


if __name__ == "__main__":
    raise SystemExit(main())
