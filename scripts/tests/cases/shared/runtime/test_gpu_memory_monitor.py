"""Shared sampled-memory reporting: missing data, stage boundaries and cleanup."""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.launchers.runtime import gpu_memory
from scripts.tests.shared.paths import CasePaths


class MemoryMonitorTests(unittest.TestCase):
    def test_fast_adapter_counter_is_reused_and_closed(self):
        with CasePaths(__file__).temporary_directory() as folder:
            counter = MagicMock()
            counter.samples.return_value = [
                {"Path": r"\GPU Adapter Memory(luid_1_phys_0)\Dedicated Usage", "Value": 1024**3}
            ]
            manager = MagicMock()
            manager.__enter__.return_value = counter
            with patch(
                "scripts.launchers.runtime.windows_gpu_counter.WindowsAdapterCounter", return_value=manager
            ) as create:
                monitor = gpu_memory.GpuMemoryMonitor(None, Path(folder) / "fast.jsonl", fast_windows=True)
                with monitor:
                    deadline = time.monotonic() + 2
                    while not monitor.samples and time.monotonic() < deadline:
                        monitor._stop.wait(0.001)
                create.assert_called_once()
                manager.__exit__.assert_called_once()
            self.assertEqual(monitor.summary()["poll_pause_s"], 0.1)
            self.assertEqual(monitor.summary()["peak_total_used_mb"], 1024)
            with self.assertRaises(ValueError):
                gpu_memory.GpuMemoryMonitor(123, Path(folder) / "bad", fast_windows=True)

    def test_brief_peaks_and_missing_samples_are_not_reported_as_sustained(self):
        samples = [
            {"seconds": second, "stage": "measured", "memory": None if value is None else {"used_mb": value}}
            for second, value in [(0, 10000), (4, 13200), (8, 10000), (12, 13300), (16, None), (20, 13200)]
        ]
        summary = gpu_memory.sampled_usage(samples)
        self.assertEqual(summary["median_used_mb"], 13200)
        windows = summary["near_peak_windows"]
        self.assertEqual([window["sample_count"] for window in windows], [1, 1, 1])
        self.assertEqual([window["first_sample_seconds"] for window in windows], [4, 12, 20])
        self.assertEqual(windows[0]["first_sample_seconds"], windows[0]["last_sample_seconds"])

    def test_query_crossing_a_stage_boundary_is_not_a_decode_peak(self) -> None:
        monitor = gpu_memory.GpuMemoryMonitor(42, Path("unused"))
        monitor.stage = "SamplerCustomAdvanced"

        def transition(_: int) -> gpu_memory.GpuMemorySnapshot:
            monitor.stage = "VAEDecodeTiled"
            return gpu_memory.GpuMemorySnapshot(12000, None, 11000)

        with patch.object(gpu_memory, "get_gpu_memory_snapshot", side_effect=transition):
            monitor.samples.append(monitor._sample())
        sample = monitor.samples[0]
        self.assertEqual(sample["stage"], "transition")
        self.assertEqual(sample["stage_start"], "SamplerCustomAdvanced")
        self.assertEqual(sample["stage_end"], "VAEDecodeTiled")
        self.assertNotIn("VAEDecodeTiled", monitor.summary()["stage_peaks"])

    def test_stage_peaks_and_missing_process_data(self) -> None:
        with CasePaths(__file__).temporary_directory() as folder:
            monitor = gpu_memory.GpuMemoryMonitor(42, Path(folder) / "vram.jsonl")
            with patch.object(
                gpu_memory,
                "get_gpu_memory_snapshot",
                side_effect=[
                    gpu_memory.GpuMemorySnapshot(8000, 16000, 7000),
                    gpu_memory.GpuMemorySnapshot(12000, 16000, None),
                    None,
                ],
            ):
                monitor.stage = "SamplerCustomAdvanced"
                monitor.samples.append(monitor._sample())
                monitor.stage = "VAEDecodeTiled"
                monitor.samples.append(monitor._sample())
                monitor.samples.append(monitor._sample())
            summary = monitor.summary()
            self.assertEqual(summary["available_samples"], 2)
            self.assertEqual(summary["peak_total_used_mb"], 12000)
            self.assertEqual(summary["peak_process_used_mb"], 7000)
            self.assertEqual(summary["minimum_available_mb"], 4000)
            self.assertIsNone(summary["stage_peaks"]["VAEDecodeTiled"]["process_used_mb"])

    def test_unavailable_and_disabled_are_not_zero_usage(self) -> None:
        monitor = gpu_memory.GpuMemoryMonitor(42, Path("unused"), enabled=False)
        with monitor:
            pass
        self.assertEqual(monitor.summary()["status"], "disabled")
        self.assertIsNone(monitor.summary()["peak_total_used_mb"])
        monitor.enabled = True
        self.assertEqual(monitor.summary()["status"], "unavailable")

    def test_polling_thread_records_and_stops_after_failure(self) -> None:
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "vram.jsonl"
            with patch.object(gpu_memory, "get_gpu_memory_snapshot", return_value=None):
                monitor = gpu_memory.GpuMemoryMonitor(42, path)
                with self.assertRaisesRegex(RuntimeError, "generation failed"), monitor:
                    # Wait only for the first mocked query, not a real counter.
                    deadline = time.monotonic() + 2
                    while not monitor.samples and time.monotonic() < deadline:
                        monitor._stop.wait(0.001)
                    self.assertTrue(monitor.samples)
                    raise RuntimeError("generation failed")
            assert monitor._thread is not None
            self.assertFalse(monitor._thread.is_alive())
            self.assertIsNone(json.loads(path.read_text(encoding="utf-8").splitlines()[0])["memory"])


if __name__ == "__main__":
    unittest.main()
