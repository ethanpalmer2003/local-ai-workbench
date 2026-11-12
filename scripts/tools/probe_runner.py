"""Run one probe module under a hard wall-clock deadline.

A probe is expected to finish quickly, and its inner request timeouts only bound one read: an engine
that accepts a request and never answers would otherwise hold the row for minutes. This runner is the
supervisor - it kills the child at the deadline and reports `ProbeTimeout`, because a guard inside the
child cannot preempt a blocking call on Windows.
"""

import argparse
import subprocess
import sys
import time

from scripts.config import project_config as project_cfg

# - whole-run budgets for the quick probe capabilities, in seconds
BUDGETS = {
    "benchmark_specspeed": 180,
    "benchmark_ngram": 300,
    "benchmark_context_stream": 300,
    "benchmark_backends": 300,
}
DEFAULT_BUDGET = 180
TIMEOUT_STATUS = 124


def budget_for(module: str) -> int:
    """The whole-run budget for one probe module name."""
    return BUDGETS.get(module.rsplit(".", 1)[-1], DEFAULT_BUDGET)


def run(command: list[str], seconds: float) -> int:
    """Run a command and kill it when the deadline passes; `TIMEOUT_STATUS` means it fired."""
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=str(project_cfg.BASE_DIR), stdin=subprocess.DEVNULL)
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=30)
        print(
            f"[FAIL] ProbeTimeout: {' '.join(command[:3])} exceeded its {seconds:.0f} s deadline after "
            f"{time.perf_counter() - started:.0f} s",
            flush=True,
        )
        return TIMEOUT_STATUS


def run_module(module: str, seconds: float) -> int:
    return run([sys.executable, "-m", module], seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", help="module to run, for example scripts.benchmarks.llamacpp.benchmark_ngram")
    parser.add_argument("--deadline", type=float, help="whole-run budget in seconds (default: per-module)")
    args = parser.parse_args(argv)
    seconds = args.deadline if args.deadline is not None else budget_for(args.module)
    return run_module(args.module, seconds)


if __name__ == "__main__":
    raise SystemExit(main())
