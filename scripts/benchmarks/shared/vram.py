"""Automatic VRAM evidence for live benchmark backend sessions."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.paths import RunPaths
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor, get_gpu_memory_snapshot

MEMORY_SOURCE = "Windows dedicated-memory counters; per-process allocations and whole-adapter usage are distinct"


def snapshot_dict(pid: int | None = None) -> dict[str, Any] | None:
    """Serialized GPU counters, or None when the counters are unavailable."""
    snapshot = get_gpu_memory_snapshot(pid)
    return None if snapshot is None else asdict(snapshot)


def process_evidence(
    monitor: GpuMemoryMonitor,
    baseline: dict[str, Any] | None,
    resident: dict[str, Any] | None,
    trace: Path,
    source: str = MEMORY_SOURCE,
) -> dict[str, Any]:
    """Per-process VRAM evidence: monitor summary plus baseline, resident snapshot and trace."""
    return {**monitor.summary(), "baseline": baseline, "resident": resident, "trace": str(trace), "source": source}


class BenchmarkVram:
    def __init__(self, run: RunPaths, context: dict[str, Any], *, fast_adapter_sampling: bool = False) -> None:
        self.run = run
        self.context = context
        self.adapter = GpuMemoryMonitor(None, run.logs / "vram-adapter.jsonl", fast_windows=fast_adapter_sampling)
        self.adapter.stage = "startup"
        self.processes: dict[str, list[tuple[int, GpuMemoryMonitor, object]]] = {}
        self.baseline: object = None

    def __enter__(self) -> "BenchmarkVram":
        snapshot = get_gpu_memory_snapshot()
        self.baseline = None if snapshot is None else asdict(snapshot)
        self.adapter.__enter__()
        return self

    @property
    def stage(self) -> str:
        return self.adapter.stage

    @stage.setter
    def stage(self, value: str) -> None:
        self.adapter.stage = value
        for processes in self.processes.values():
            for _, monitor, _ in processes:
                monitor.stage = value

    def watch_backend(self, name: str, pids: list[int]) -> None:
        self.processes[name] = []
        for pid in pids:
            snapshot = get_gpu_memory_snapshot(pid)
            monitor = GpuMemoryMonitor(pid, self.run.logs / f"vram-{name}-{pid}.jsonl")
            monitor.stage = "ready"
            self.processes[name].append((pid, monitor, None if snapshot is None else asdict(snapshot)))
            monitor.__enter__()

    def __exit__(self, *_args: object) -> None:
        self.adapter.__exit__()
        for processes in self.processes.values():
            for _, monitor, _ in processes:
                monitor.__exit__()
        summary: dict[str, Any] = {
            "execution_context": self.context,
            "baseline": self.baseline,
            "adapter": self.adapter.summary(),
            "backends": {
                name: {
                    "status": "identified" if processes else "process_unavailable",
                    "processes": [
                        {"pid": pid, "resident": resident, **monitor.summary()} for pid, monitor, resident in processes
                    ],
                }
                for name, processes in self.processes.items()
            },
            "limits": [
                "Sampled peaks can miss transients; polling adds overhead.",
                "Process values include descendants; overlapping trees must not be added together.",
                "Windows process allocations can exceed physical dedicated-memory use.",
                "Missing measurements are null; no zero-use assumption.",
            ],
        }
        (self.run.artifacts / "vram.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        peak = summary["adapter"]["peak_total_used_mb"]
        lines = [
            "# VRAM",
            "",
            f"- Adapter sampled peak: {peak if peak is not None else 'unavailable'} MiB.",
            "- Baseline, ready-state process usage and stage peaks: [vram.json](vram.json).",
            "- Raw samples: ../logs/vram-*.jsonl.",
            "- Sampled peaks may miss transients; polling adds overhead.",
            "- Typical usage and >=95%-of-peak sample windows: usage_distribution in vram.json, including per-stage values. Sample windows do not measure continuous peak duration.",
        ]
        (self.run.artifacts / "vram.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = self.run.artifacts / "report.json"
        if report.exists():
            self.run.write_report(json.loads(report.read_text(encoding="utf-8")))
        print(f"[VRAM] {self.run.artifacts / 'vram.json'}", flush=True)
