import argparse
import json
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path

from scripts.launchers.runtime.gpu_memory import get_gpu_memory_snapshot, report_vram_usage
from scripts.launchers.llamacpp.llamacpp import LlamaMonitor


def run_server(cmd: list[str], cwd: Path, startup_marker: Path, log_file: Path) -> int:
    before = get_gpu_memory_snapshot()
    process = subprocess.Popen(cmd, cwd=cwd)

    def startup_summary() -> None:
        while process.poll() is None:
            if startup_marker.exists():
                startup_marker.unlink()
                monitor = LlamaMonitor(log_file)
                monitor.print_summary()
                measured = report_vram_usage("LlamaCpp Server", process.pid, before)
                report = {
                    "native": asdict(monitor.allocation_report()),
                    "measured": asdict(measured) if measured else None,
                }
                log_file.with_suffix(".memory.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                return
            time.sleep(0.2)

    threading.Thread(target=startup_summary, daemon=True).start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--startup-marker", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    return run_server(cmd, args.cwd, args.startup_marker, args.log_file)


if __name__ == "__main__":
    raise SystemExit(main())
