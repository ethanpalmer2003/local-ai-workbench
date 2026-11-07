"""Resource telemetry preserves phase boundaries, missing values and owned RAM guards."""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.tests.shared import resources
from scripts.tests.shared.process_fixtures import running_process


class ResourceTests(unittest.TestCase):
    def test_owned_monitor_preserves_unknown_gpu_and_summarizes_after_failure(self):
        from pathlib import Path
        gpu = MagicMock()
        gpu.summary.return_value = {"peak_process_used_mb": None}
        result = {}
        with patch("scripts.launchers.runtime.gpu_memory.GpuMemoryMonitor", return_value=gpu) as factory, patch.object(resources, "watch_resources"), self.assertRaisesRegex(RuntimeError, "fixture"):
            with resources.monitor_process(running_process(pid=123), Path("unused.jsonl")) as result:
                raise RuntimeError("fixture")
        factory.assert_called_once_with(123, Path("unused.jsonl"))
        self.assertEqual(result["gpu"]["peak_process_used_mb"], None)
        self.assertEqual(result["pid"], 123)
        self.assertEqual(result["cpu_ram"]["whole_run"]["process_rss_bytes"]["maximum"], None)

    def test_short_process_exit_before_sampling_is_unavailable(self):
        import psutil

        samples = []
        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(123)):
            resources.watch_resources(running_process(pid=123), threading.Event(), samples, time.monotonic() + 1)
        self.assertEqual(samples, [])

    def test_free_ram_above_configured_floor_does_not_abort(self):
        process, target, stop = running_process(pid=123), MagicMock(), MagicMock()
        stop.is_set.side_effect = [False, True]
        target.cpu_times.return_value = SimpleNamespace(user=1, system=0)
        target.io_counters.return_value = SimpleNamespace(read_bytes=0, write_bytes=0)
        target.memory_info.return_value = SimpleNamespace(rss=100)
        samples = []
        with (
            patch.object(resources.benchmark_cfg, "MINIMUM_FREE_RAM_GIB", 1.25),
            patch("psutil.Process", return_value=target),
            patch("psutil.virtual_memory", return_value=SimpleNamespace(available=1.5 * 2**30, percent=95)),
            patch("psutil.disk_io_counters", return_value=None),
            patch.object(resources.launch_util, "kill_process_tree") as kill,
        ):
            resources.watch_resources(process, stop, samples, time.monotonic() + 60)
        kill.assert_not_called()
        self.assertEqual(resources.summarize_resources(samples)["guards"]["minimum_free_ram_gib"], [1.25])

    def test_phase_summary_keeps_missing_data_and_counter_reset_unknown(self):
        rows = [
            {"phase": "startup", "process_cpu_percent_machine": 90, "system_disk_read_bytes": 100},
            {
                "phase": "measured",
                "process_cpu_percent_machine": 10,
                "system_disk_read_bytes": 200,
                "process_io_read_bytes": 50,
            },
            {
                "phase": "measured",
                "process_cpu_percent_machine": 20,
                "system_disk_read_bytes": 200,
                "process_io_read_bytes": 20,
            },
        ]
        result = resources.summarize_resources(rows)["phases"]["measured"]
        self.assertEqual(result["process_cpu_percent_machine"]["median"], 15)
        self.assertEqual(result["system_disk_read_bytes_delta"], 0)
        self.assertIsNone(result["process_io_read_bytes_delta"])
        self.assertIsNone(result["process_rss_bytes"]["maximum"])

    def test_ram_guard_stops_only_owned_process_and_does_not_invent_cpu_sample(self):
        process, target = running_process(pid=123), MagicMock()
        target.cpu_times.return_value = SimpleNamespace(user=1, system=0.5)
        target.io_counters.return_value = SimpleNamespace(read_bytes=10, write_bytes=5)
        target.memory_info.return_value = SimpleNamespace(rss=100)
        target.oneshot.return_value.__enter__.return_value = target
        samples = []
        with (
            patch("psutil.Process", return_value=target),
            patch("psutil.cpu_count", return_value=16),
            patch("psutil.cpu_percent", return_value=30),
            patch("psutil.virtual_memory", return_value=SimpleNamespace(available=2**29, percent=98)),
            patch("psutil.disk_io_counters", return_value=None),
            patch.object(resources.launch_util, "kill_process_tree") as kill,
        ):
            resources.watch_resources(process, threading.Event(), samples, time.monotonic() + 60, lambda: "startup")
        kill.assert_called_once_with(123)
        self.assertIn("abort", samples[0])
        self.assertEqual(samples[0]["guard_minimum_free_ram_gib"], resources.benchmark_cfg.MINIMUM_FREE_RAM_GIB)
        self.assertIsNone(samples[0]["process_cpu_percent_machine"])
        self.assertIsNone(samples[0]["system_disk_read_bytes"])
