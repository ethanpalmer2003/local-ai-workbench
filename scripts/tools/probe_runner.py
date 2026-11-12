"""Run a capability module under a hard wall-clock deadline, budgeted by category.

Capability rows are not all probes. A smoke check answers one request, a probe starts an engine and
sends a few, and a benchmark measures many runs across profiles or builds. Each category gets its own
budget, so a hung engine is killed quickly instead of waiting out its inner timeouts.
"""

import argparse
import subprocess
import sys
import time

from scripts.config import project_config as project_cfg
from scripts.tools.capability_matrix import CATEGORY as _CATEGORIES

# - category -> whole-run budget in seconds; the matrix owns which category a row is
CATEGORY_SECONDS = {"smoke": 90, "probe": 300, "benchmark": 900}
DEFAULT_CATEGORY = "probe"
TIMEOUT_STATUS = 124

# - module names carry the same last segment as their capability subject
_BY_MODULE = {subject.rsplit("/", 1)[-1]: category for subject, category in _CATEGORIES.items()}


def category_for(module: str) -> str:
    """The matrix category of one module name, defaulting to a plain probe."""
    return _BY_MODULE.get(module.rsplit(".", 1)[-1], DEFAULT_CATEGORY)


def budget_for(module: str) -> int:
    """The whole-run budget for one probe module name."""
    return CATEGORY_SECONDS[category_for(module)]


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
    parser.add_argument("--category", choices=tuple(CATEGORY_SECONDS), help="override the module's category")
    parser.add_argument("--deadline", type=float, help="whole-run budget in seconds, overriding the category")
    args = parser.parse_args(argv)
    category = args.category or category_for(args.module)
    seconds = args.deadline if args.deadline is not None else CATEGORY_SECONDS[category]
    print(f"[budget] {args.module} category={category} deadline={seconds:.0f}s", flush=True)
    return run_module(args.module, seconds)


if __name__ == "__main__":
    raise SystemExit(main())
