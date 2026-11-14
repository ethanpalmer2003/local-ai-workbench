"""Sample task-owned process resources and system activity on the benchmark clock."""

import statistics
import time
from contextlib import contextmanager
from typing import Any

from scripts.launchers import launch_util
from scripts.shared import benchmark_config as benchmark_cfg


@contextmanager
def monitor_process(process, gpu_log, *, seconds=240, phase=lambda: "resident", worker_module=None):
    """Reuse CPU/RSS and GPU samplers for one owned process; absent counters stay unknown."""
    import threading

    from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor
    from scripts.launchers.shared.services.process import owned_module_worker

    launcher_pid = process.pid
    if worker_module:
        process = owned_module_worker(process, worker_module)

    stop, samples, result = threading.Event(), [], {}
    worker = threading.Thread(
        target=watch_resources, args=(process, stop, samples, time.monotonic() + seconds, phase), daemon=True
    )
    gpu = GpuMemoryMonitor(process.pid, gpu_log)
    try:
        with gpu:
            worker.start()
            try:
                yield result
            finally:
                stop.set()
                worker.join(timeout=5)
    finally:
        result.update(
            pid=process.pid, launcher_pid=launcher_pid, cpu_ram=summarize_resources(samples), gpu=gpu.summary()
        )


def watch_resources(process, stop, samples, deadline, phase=lambda: "unknown", clock_origin=None):
    import psutil

    logical = psutil.cpu_count() or 1
    try:
        target = psutil.Process(process.pid)
        target.cpu_percent()
    except psutil.NoSuchProcess:
        return
    psutil.cpu_percent()
    started = time.monotonic() if clock_origin is None else clock_origin
    previous = None
    minimum_free_ram_gib = benchmark_cfg.MINIMUM_FREE_RAM_GIB
    while not stop.is_set() and process.poll() is None:
        now = time.monotonic()
        memory = psutil.virtual_memory()
        disk = psutil.disk_io_counters()
        sample: dict[str, Any] = {
            "time": time.time(),
            "seconds": now - started,
            "phase": phase(),
            "logical_cpus": logical,
            "available_gib": memory.available / 2**30,
            "guard_minimum_free_ram_gib": minimum_free_ram_gib,
            "system_ram_used_percent": memory.percent,
            "system_cpu_percent": psutil.cpu_percent() if previous else None,
            "process_rss_bytes": None,
            "process_cpu_percent_machine": None,
            "process_cpu_percent_one_core": None,
            "process_cpu_seconds": None,
            "process_io_read_bytes": None,
            "process_io_write_bytes": None,
            "system_disk_read_bytes": disk.read_bytes if disk else None,
            "system_disk_write_bytes": disk.write_bytes if disk else None,
        }
        try:
            with target.oneshot():
                sample["process_rss_bytes"] = target.memory_info().rss
                cpu = target.cpu_percent() if previous else None
                times = target.cpu_times()
                io = target.io_counters()
                sample.update(
                    process_cpu_percent_one_core=cpu,
                    process_cpu_percent_machine=cpu / logical if cpu is not None else None,
                    process_cpu_seconds=times.user + times.system,
                    process_io_read_bytes=io.read_bytes,
                    process_io_write_bytes=io.write_bytes,
                )
        except (psutil.Error, AttributeError):
            pass
        for name in ("system_disk_read_bytes", "system_disk_write_bytes"):
            current, before = sample[name], previous.get(name) if previous else None
            sample[name + "_per_second"] = (
                (current - before) / (now - previous["_monotonic"])
                if previous is not None and current is not None and before is not None and current >= before
                else None
            )
        sample["_monotonic"] = now
        samples.append(sample)
        previous = sample
        if sample["available_gib"] < minimum_free_ram_gib or now > deadline:
            sample["abort"] = f"Available RAM below {minimum_free_ram_gib} GiB or whole-run budget exhausted"
            launch_util.kill_process_tree(process.pid)
            return
        stop.wait(0.5)


def summarize_resources(samples: list[dict[str, Any]]) -> dict[str, Any]:
    def summary(rows):
        data = {}
        for name in (
            "system_cpu_percent",
            "process_cpu_percent_machine",
            "process_rss_bytes",
            "system_disk_read_bytes_per_second",
            "system_disk_write_bytes_per_second",
        ):
            values = [row[name] for row in rows if row.get(name) is not None]
            data[name] = {
                "median": statistics.median(values) if values else None,
                "maximum": max(values) if values else None,
            }
        for name in (
            "process_cpu_seconds",
            "process_io_read_bytes",
            "process_io_write_bytes",
            "system_disk_read_bytes",
            "system_disk_write_bytes",
        ):
            values = [row[name] for row in rows if row.get(name) is not None]
            data[name + "_delta"] = values[-1] - values[0] if len(values) > 1 and values[-1] >= values[0] else None
        return data

    return {
        "guards": {
            "minimum_free_ram_gib": sorted(
                {row["guard_minimum_free_ram_gib"] for row in samples if "guard_minimum_free_ram_gib" in row}
            ),
            "whole_run_deadline_enforced": any("guard_minimum_free_ram_gib" in row for row in samples),
        },
        "whole_run": summary(samples),
        "phases": {
            phase: summary([row for row in samples if row["phase"] == phase])
            for phase in dict.fromkeys(row["phase"] for row in samples)
        },
        "limits": [
            "CPU process percent normalized to total logical CPUs; one-core scale also retained in trace.",
            "Process data is server PID only. System CPU/disk includes other applications.",
            "Process I/O counters are not physical SSD bytes; cached/mapped/network I/O can differ.",
            "System disk counters aggregate disks; no SSD-specific busy time, queue depth or wear measured.",
            "OS/shader/file caches not reset; null means unavailable. Samples about 0.5 seconds apart.",
        ],
    }
