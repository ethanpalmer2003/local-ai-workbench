"""AMD GPU memory:
- snapshots and launch-time reporting
"""

import contextlib
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GpuReportingSettings:
    query_timeout_s: float = 5
    poll_interval_s: float = 2
    stable_checks: int = 3
    stable_timeout_s: float = 180


GPU_SETTINGS = GpuReportingSettings()


@dataclass(frozen=True)
class GpuMemorySnapshot:
    used_mb: float
    total_mb: float | None
    process_used_mb: float | None
    other_ai_mb: float | None = None
    other_non_ai_mb: float | None = None
    adapter_id: str | None = None

    @property
    def available_mb(self) -> float | None:
        return None if self.total_mb is None else max(self.total_mb - self.used_mb, 0.0)

    @property
    def other_used_mb(self) -> float | None:
        return None if self.process_used_mb is None else max(self.used_mb - self.process_used_mb, 0.0)


@dataclass(frozen=True)
class GpuMemoryReport:
    before: GpuMemorySnapshot
    measured: GpuMemorySnapshot
    stable: bool


class GpuMemoryMonitor:
    """Sample shared OS GPU counters without blocking the generation event loop."""

    def __init__(self, pid: int | None, log_path: Path, *, enabled: bool = True, fast_windows: bool = False) -> None:
        if fast_windows and pid is not None:
            raise ValueError("Persistent PDH fast sampling is adapter-only; process sampling remains separate")
        self.pid = pid
        self.log_path = log_path
        self.enabled = enabled
        self.fast_windows = fast_windows
        self.stage = "submission"
        self.samples: list[dict[str, Any]] = []
        self.started = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "GpuMemoryMonitor":
        if self.enabled:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _sample(self, reader: Callable[[], GpuMemorySnapshot | None] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        stage = self.stage
        snapshot = reader() if reader else get_gpu_memory_snapshot(self.pid)
        return {
            "seconds": time.monotonic() - self.started,
            "query_seconds": time.monotonic() - started,
            "stage": stage if stage == self.stage else "transition",
            "stage_start": stage,
            "stage_end": self.stage,
            "memory": None if snapshot is None else {**asdict(snapshot), "available_mb": snapshot.available_mb},
        }

    def _run(self) -> None:
        with self.log_path.open("w", encoding="utf-8") as stream, contextlib.ExitStack() as stack:
            reader = None
            if self.fast_windows:
                try:
                    from scripts.launchers.runtime.windows_gpu_counter import WindowsAdapterCounter

                    counter = stack.enter_context(WindowsAdapterCounter())

                    def read_counter() -> GpuMemorySnapshot | None:
                        return parse_windows_memory(counter.samples(), set(), {})

                    reader = read_counter
                except Exception as error:
                    sample = {
                        "seconds": time.monotonic() - self.started,
                        "stage": self.stage,
                        "memory": None,
                        "error": str(error),
                    }
                    self.samples.append(sample)
                    stream.write(json.dumps(sample) + "\n")
                    return
            while not self._stop.is_set():
                try:
                    sample = self._sample(reader)
                except Exception as error:
                    sample = {
                        "seconds": time.monotonic() - self.started,
                        "stage": self.stage,
                        "memory": None,
                        "error": str(error),
                    }
                self.samples.append(sample)
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                self._stop.wait(0.1 if self.fast_windows else GPU_SETTINGS.poll_interval_s)

    def summary(self) -> dict[str, Any]:
        valid = [sample for sample in self.samples if sample["memory"] is not None]

        def peak(samples: list[dict[str, Any]], field: str) -> float | None:
            values = [sample["memory"][field] for sample in samples if sample["memory"][field] is not None]
            return max(values) if values else None

        available = [
            sample["memory"]["available_mb"] for sample in valid if sample["memory"]["available_mb"] is not None
        ]
        return {
            "status": "disabled" if not self.enabled else "sampled" if valid else "unavailable",
            "units": "MiB (existing *_mb field names)",
            "poll_pause_s": 0.1 if self.fast_windows else GPU_SETTINGS.poll_interval_s,
            "source": "persistent Windows PDH adapter counter" if self.fast_windows else "platform snapshot",
            "max_query_s": max((sample.get("query_seconds", 0.0) for sample in self.samples), default=0.0),
            "peak_kind": "sampled lower bound; query time is additional to the poll pause",
            "samples": len(self.samples),
            "available_samples": len(valid),
            "peak_total_used_mb": peak(valid, "used_mb"),
            "peak_process_used_mb": peak(valid, "process_used_mb"),
            "minimum_available_mb": min(available) if available else None,
            "usage_distribution": sampled_usage(self.samples),
            "process_usage_distribution": sampled_usage(self.samples, "process_used_mb"),
            "stage_peaks": {
                stage: {
                    "total_used_mb": peak([s for s in valid if s["stage"] == stage], "used_mb"),
                    "process_used_mb": peak([s for s in valid if s["stage"] == stage], "process_used_mb"),
                    "usage_distribution": sampled_usage([s for s in self.samples if s["stage"] == stage]),
                }
                for stage in dict.fromkeys(sample["stage"] for sample in valid)
            },
        }


def sampled_usage(samples: list[dict[str, Any]], field: str = "used_mb") -> dict[str, Any]:
    values = [
        sample["memory"][field]
        for sample in samples
        if sample.get("memory") is not None and sample["memory"].get(field) is not None
    ]
    threshold = max(values) * 0.95 if values else None
    windows: list[dict[str, Any]] = []
    current = None
    for sample in samples:
        memory = sample.get("memory")
        if memory is None or memory.get(field) is None or threshold is None or memory[field] < threshold:
            current = None
            continue
        if current is None:
            current = {
                "first_sample_seconds": sample["seconds"],
                "last_sample_seconds": sample["seconds"],
                "sample_count": 0,
            }
            windows.append(current)
        current["last_sample_seconds"] = sample["seconds"]
        current["sample_count"] += 1
    return {
        "minimum_used_mb": min(values) if values else None,
        "median_used_mb": statistics.median(values) if values else None,
        "near_peak_threshold_mb": threshold,
        "near_peak_fraction": 0.95,
        "near_peak_windows": windows,
        "timing_limit": "Consecutive samples at >=95% of sampled peak; sample spans are not continuous-duration measurements. Missing samples break windows. Query time adds to poll pause.",
    }


_BUFFER_LINE = re.compile(r"^\S+:\s+(\S+)\s+(?:model|KV|compute) buffer size\s*=\s*([\d.]+)\s*MiB", re.IGNORECASE)


def parse_koboldcpp_buffer_report(log_path: str) -> dict[str, float]:
    """Sum koboldcpp's own startup-log buffer-size lines (model + KV + compute) per device.
    - what the loader itself declares it allocated - deterministic and tied directly to config
      (moecpu, gpulayers, context size, etc)
    - unlike the OS-level GPU counter snapshot, which also picks up driver overhead,
      other processes, and polling-timing noise
    """
    totals: dict[str, float] = {}
    try:
        with open(log_path, encoding="utf-8", errors="replace") as log_file:
            text = log_file.read()
    except OSError:
        return totals
    for line in text.splitlines():
        match = _BUFFER_LINE.match(line.strip())
        if match:
            device, mib = match.group(1), float(match.group(2))
            totals[device] = totals.get(device, 0.0) + mib
    return totals


def _memory_value(data: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, (int, float, str)):
            try:
                return float(value) / (1024 * 1024)
            except ValueError:
                pass
    return None


def _get_windows_processes(pid: int) -> tuple[set[int], dict[int, tuple[str, str]]]:
    script = "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=GPU_SETTINGS.query_timeout_s,
            check=False,
        )
        processes = json.loads(result.stdout)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return {pid}, {}

    if isinstance(processes, dict):
        processes = [processes]
    if not isinstance(processes, list):
        return {pid}, {}

    children: dict[int, list[int]] = {}
    details: dict[int, tuple[str, str]] = {}
    for process in processes:
        if not isinstance(process, dict):
            continue
        process_id = process.get("ProcessId")
        parent_id = process.get("ParentProcessId")
        name = process.get("Name")
        command_line = process.get("CommandLine")
        if isinstance(process_id, int) and isinstance(parent_id, int):
            children.setdefault(parent_id, []).append(process_id)
            details[process_id] = (str(name or ""), str(command_line or ""))

    result_ids = {pid}
    pending = [pid]
    while pending:
        parent_id = pending.pop()
        for child_id in children.get(parent_id, []):
            if child_id not in result_ids:
                result_ids.add(child_id)
                pending.append(child_id)
    return result_ids, details


_AI_PROCESS_NAMES = {
    "koboldcpp.exe",
    "koboldcpp-nocuda.exe",
    "audiocpp_server.exe",
    "llama-server.exe",
    "sd-server.exe",
}


def _is_ai_process(details: tuple[str, str]) -> bool:
    name, command_line = details
    name = name.lower()
    command_line = command_line.lower()
    return name in _AI_PROCESS_NAMES or (name in {"python.exe", "pythonw.exe"} and "scripts" in command_line)


def _adapter_key(path: str) -> str | None:
    match = re.search(r"(luid_[^\\]+)", path)
    return match.group(1) if match else None


def _get_windows_memory(pid: int | None) -> GpuMemorySnapshot | None:
    if sys.platform != "win32":
        return None

    target_pids, process_names = _get_windows_processes(pid) if pid is not None else (set(), {})
    script = (
        "$c = Get-Counter -Counter "
        "'\\GPU Adapter Memory(*)\\Dedicated Usage','\\GPU Process Memory(*)\\Dedicated Usage'; "
        "$c.CounterSamples | ForEach-Object { [PSCustomObject]@{Path=$_.Path;Value=$_.CookedValue} } | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=GPU_SETTINGS.query_timeout_s,
            check=False,
        )
        samples = json.loads(result.stdout)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None

    return parse_windows_memory(samples, target_pids, process_names)


def _collect_samples(samples: object) -> tuple[dict[str, float], list[tuple[str, int, float]]]:
    """Split Get-Counter JSON into adapter totals (MB) and per-process usage (MB)."""
    entries = [samples] if isinstance(samples, dict) else samples
    adapter_mb: dict[str, float] = {}
    process_samples: list[tuple[str, int, float]] = []
    if not isinstance(entries, list):
        return adapter_mb, process_samples
    for sample in entries:
        if not isinstance(sample, dict):
            continue
        path = str(sample.get("Path", "")).lower()
        value = sample.get("Value")
        if not isinstance(value, (int, float)):
            continue
        adapter = _adapter_key(path)
        if adapter is None:
            continue
        value_mb = float(value) / (1024 * 1024)
        if "gpu adapter memory" in path:
            adapter_mb[adapter] = adapter_mb.get(adapter, 0.0) + value_mb
        elif "gpu process memory" in path:
            match = re.search(r"pid_(\d+)", path)
            if match:
                process_samples.append((adapter, int(match.group(1)), value_mb))
    return adapter_mb, process_samples


def _attribute_usage(
    adapter_mb: dict[str, float], process_samples: list[tuple[str, int, float]], target_pids: set[int]
) -> dict[str, float]:
    return {
        adapter: sum(
            value for key, process_id, value in process_samples if key == adapter and process_id in target_pids
        )
        for adapter in adapter_mb
    }


def _selected_adapter(adapter_mb: dict[str, float], target_usage: dict[str, float]) -> str:
    """Prefer the adapter our own pids touch; fall back to the busiest one."""
    selection = target_usage if max(target_usage.values(), default=0.0) else adapter_mb
    return max(selection, key=lambda adapter: selection[adapter])


def _split_process_memory(
    process_samples: list[tuple[str, int, float]],
    selected_adapter: str,
    target_pids: set[int],
    process_names: dict[int, tuple[str, str]],
) -> tuple[float | None, float | None, float | None]:
    process_mb: float | None = None
    other_ai_mb: float | None = None
    other_non_ai_mb: float | None = None
    for adapter, process_id, value_mb in process_samples:
        if adapter != selected_adapter:
            continue
        if process_id in target_pids:
            process_mb = (process_mb or 0.0) + value_mb
        elif _is_ai_process(process_names.get(process_id, ("", ""))):
            other_ai_mb = (other_ai_mb or 0.0) + value_mb
        else:
            other_non_ai_mb = (other_non_ai_mb or 0.0) + value_mb
    return process_mb, other_ai_mb, other_non_ai_mb


def parse_windows_memory(
    samples: object, target_pids: set[int], process_names: dict[int, tuple[str, str]]
) -> GpuMemorySnapshot | None:
    adapter_mb, process_samples = _collect_samples(samples)
    if not adapter_mb:
        return None
    selected = _selected_adapter(adapter_mb, _attribute_usage(adapter_mb, process_samples, target_pids))
    process_mb, other_ai_mb, other_non_ai_mb = _split_process_memory(
        process_samples, selected, target_pids, process_names
    )

    # - use the adapter-wide counter for the total: the sum of per-process
    #   counters can exceed physical dedicated-memory usage because Windows
    #   reports some allocations in more than one process/category
    return GpuMemorySnapshot(adapter_mb[selected], None, process_mb, other_ai_mb, other_non_ai_mb, selected)


def _get_rocm_memory() -> tuple[float, float | None] | None:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True,
            text=True,
            timeout=GPU_SETTINGS.query_timeout_s,
            check=False,
        )
        data = json.loads(result.stdout)
        used_mb = total_mb = 0.0
        found_total = False
        for gpu in data.values():
            if not isinstance(gpu, dict):
                continue
            used = _memory_value(gpu, "VRAM Total Used Memory (B)")
            total = _memory_value(gpu, "VRAM Total Memory (B)", "VRAM Total Memory")
            if used is not None:
                used_mb += used
            if total is not None:
                total_mb += total
                found_total = True
        return used_mb, total_mb if found_total else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None


def _parse_memory_mb(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) / (1024 * 1024)
    if not isinstance(value, str):
        return None
    parts = value.strip().upper().split()
    if len(parts) != 2:
        return None
    try:
        amount = float(parts[0])
    except ValueError:
        return None
    multipliers = {"B": 1 / (1024 * 1024), "KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}
    multiplier = multipliers.get(parts[1])
    return amount * multiplier if multiplier is not None else None


def _find_vram(value: object) -> float | None:
    """Depth-first search for the first VRAM figure in amd-smi JSON."""
    if isinstance(value, dict):
        normalized = {str(key).lower(): child for key, child in value.items()}
        memory = normalized.get("memory_usage", normalized)
        if isinstance(memory, dict):
            memory = {str(key).lower(): child for key, child in memory.items()}
            memory = memory.get("vram_mem", memory.get("vram", memory.get("vram_memory")))
        if (parsed := _parse_memory_mb(memory)) is not None:
            return parsed
        for child in value.values():
            if (parsed := _find_vram(child)) is not None:
                return parsed
    elif isinstance(value, list):
        for child in value:
            if (parsed := _find_vram(child)) is not None:
                return parsed
    return None


def _get_process_vram(pid: int) -> float | None:
    try:
        result = subprocess.run(
            ["amd-smi", "process", "--pid", str(pid), "--general", "--json"],
            capture_output=True,
            text=True,
            timeout=GPU_SETTINGS.query_timeout_s,
            check=False,
        )
        data = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return _find_vram(data)


def get_gpu_memory_snapshot(pid: int | None = None) -> GpuMemorySnapshot | None:
    if snapshot := _get_windows_memory(pid):
        return snapshot

    memory = _get_rocm_memory()
    if memory is None:
        return None
    used_mb, total_mb = memory
    return GpuMemorySnapshot(used_mb, total_mb, _get_process_vram(pid) if pid is not None else None)


def _poll_vram_until_stable(before: GpuMemorySnapshot, pid: int) -> tuple[GpuMemorySnapshot, bool] | None:
    last = current = before
    stable = 0
    deadline = time.monotonic() + GPU_SETTINGS.stable_timeout_s
    while time.monotonic() < deadline:
        time.sleep(GPU_SETTINGS.poll_interval_s)
        current = get_gpu_memory_snapshot(pid)
        if current is None:
            return None
        if abs(current.used_mb - last.used_mb) < 50:
            stable += 1
            if stable >= GPU_SETTINGS.stable_checks:
                break
        else:
            stable = 0
        last = current
    return current, stable >= GPU_SETTINGS.stable_checks


def report_vram_usage(
    tag: str, pid: int, before: GpuMemorySnapshot | None, log_file: str | None = None
) -> GpuMemoryReport | None:
    if before is None:
        print(f"[{tag}] VRAM unavailable: no GPU memory snapshot was available at launch")
        return

    result = _poll_vram_until_stable(before, pid)
    if result is None:
        print(f"[{tag}] VRAM unavailable: GPU memory could not be read after loading")
        return
    current, is_stable = result
    status = "stable" if is_stable else "timeout"
    delta_gb = (current.used_mb - before.used_mb) / 1024
    if current.process_used_mb is None:
        process = "process: unavailable"
    elif current.other_ai_mb is not None and current.other_non_ai_mb is not None:
        process = (
            f"process: {current.process_used_mb / 1024:.1f} GiB; "
            f"other AI: {current.other_ai_mb / 1024:.1f} GiB; "
            f"other non-AI: {current.other_non_ai_mb / 1024:.1f} GiB"
        )
    else:
        other_used = current.other_used_mb
        process = (
            "process: unavailable"
            if other_used is None
            else f"process: {current.process_used_mb / 1024:.1f} GiB; other: {other_used / 1024:.1f} GiB"
        )
    available = "" if current.available_mb is None else f"; available: {current.available_mb / 1024:.1f} GiB"

    reported = ""
    if log_file:
        totals = parse_koboldcpp_buffer_report(log_file)
        if totals:
            parts = "; ".join(f"{device}: {mib / 1024:.1f} GiB" for device, mib in sorted(totals.items()))
            reported = f"; reported (from log): {parts}"

    print(
        f"[{tag}] GPU memory measured ({status}): system allocation change ~{delta_gb:.1f} GiB; allocated: {current.used_mb / 1024:.1f} GiB{available}; {process}{reported}"
    )
    return GpuMemoryReport(before, current, is_stable)


def report_vram_usage_async(tag: str, pid: int, before: GpuMemorySnapshot | None, log_file: str | None = None) -> None:
    threading.Thread(target=report_vram_usage, args=(tag, pid, before, log_file), daemon=True).start()
