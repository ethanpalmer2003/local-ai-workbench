"""Read-only shared GPU monitor validation; never starts a model server."""

import argparse
import json
import os
import time

from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.timing import timed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pid", type=int, default=os.getpid(), help="Existing process to observe (default: this probe)"
    )
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error("seconds must be greater than zero and at most 60")
    paths = CasePaths(__file__).new_run()
    started = time.monotonic()
    with GpuMemoryMonitor(args.pid, paths.logs / "vram.jsonl") as monitor:
        time.sleep(args.seconds)
    summary = monitor.summary()
    (paths.artifacts / "vram.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    paths.write_report(
        {
            "name": "Read-only shared GPU monitor validation",
            "category": "probes",
            "status": summary["status"],
            "pid": args.pid,
            "total_seconds": time.monotonic() - started,
            "reasoning": "OS counters only; target-process allocation can be null without an active GPU workload.",
        }
    )
    print(f"[OUTPUT] {paths.root}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    with timed("GPU monitor validation"):
        main()
