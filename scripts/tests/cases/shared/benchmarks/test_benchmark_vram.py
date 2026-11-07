"""VRAM recording survives benchmark failures and preserves unavailable counters."""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.launchers.runtime.gpu_memory import GpuMemorySnapshot
from scripts.benchmarks.shared import vram
from scripts.tests.shared.paths import RunPaths, CasePaths


class BenchmarkVramTests(unittest.TestCase):
    def test_stage_process_and_failure_evidence_are_saved(self):
        snapshot = GpuMemorySnapshot(2000, 16000, 500)
        monitors = [MagicMock(), MagicMock()]
        for monitor in monitors:
            monitor.summary.return_value = {"status": "sampled", "peak_total_used_mb": 2400}
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(vram, "get_gpu_memory_snapshot", return_value=snapshot),
            patch.object(vram, "GpuMemoryMonitor", side_effect=monitors),
        ):
            run = RunPaths(Path(folder))
            run.create()
            run.write_report({"name": "fake", "category": "regression", "status": "failed"})
            with (
                self.assertRaisesRegex(ValueError, "generation failed"),
                vram.BenchmarkVram(run, {"test": "mocked"}) as memory,
            ):
                memory.watch_backend("audio", [42])
                memory.stage = "speech"
                self.assertEqual([monitor.stage for monitor in monitors], ["speech", "speech"])
                raise ValueError("generation failed")
            saved = json.loads((run.artifacts / "vram.json").read_text())
            self.assertEqual(saved["baseline"]["used_mb"], 2000)
            self.assertEqual(saved["backends"]["audio"]["processes"][0]["resident"]["process_used_mb"], 500)
            self.assertEqual(saved["backends"]["audio"]["processes"][0]["pid"], 42)
            self.assertEqual(json.loads((run.artifacts / "report.json").read_text())["vram_file"], "vram.json")
            for monitor in monitors:
                monitor.__exit__.assert_called_once()

    def test_missing_counter_and_process_are_explicit(self):
        monitor = MagicMock()
        monitor.summary.return_value = {"status": "unavailable", "peak_total_used_mb": None}
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(vram, "get_gpu_memory_snapshot", return_value=None),
            patch.object(vram, "GpuMemoryMonitor", return_value=monitor),
        ):
            run = RunPaths(Path(folder))
            run.create()
            with vram.BenchmarkVram(run, {}) as memory:
                memory.watch_backend("audio", [])
            saved = json.loads((run.artifacts / "vram.json").read_text())
            self.assertIsNone(saved["baseline"])
            self.assertIsNone(saved["adapter"]["peak_total_used_mb"])
            self.assertEqual(saved["backends"]["audio"]["status"], "process_unavailable")


if __name__ == "__main__":
    unittest.main()
