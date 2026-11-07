"""Swap probe ownership and failure cleanup without model inference."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.tests.cases.koboldcpp import kobold_image_swap as swap
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.process_fixtures import running_process


class SwapTests(unittest.TestCase):
    def test_stop_targets_only_the_recorded_owned_worker(self):
        with CasePaths(__file__).temporary_directory() as folder:
            paths = RunPaths(Path(folder))
            paths.create()
            probe = swap.SwapProbe(paths, {})
            process = running_process(pid=123)
            probe.active["audio"] = process
            with (
                patch.object(swap.launch_util, "kill_process_tree") as kill,
                patch.object(swap.backends, "listening", return_value=False),
                patch.object(swap.time, "sleep"),
            ):
                probe.stop_backend("audio", "audio-stop")
            kill.assert_called_once_with(123)
            self.assertNotIn("audio", probe.active)

    def test_request_failure_records_failure_and_cleans_all_owned_workers(self):
        with CasePaths(__file__).temporary_directory() as folder:
            paths = RunPaths(Path(folder))
            paths.create()
            probe = swap.SwapProbe(paths, {})
            process = running_process(pid=123)
            probe.owned.append(process)
            probe.report["native_pids"] = {"kobold-start": 456}
            probe.memory = MagicMock()
            probe.memory.summary.return_value = {}
            with (
                patch.object(probe, "start_backend"),
                patch.object(probe, "speech", side_effect=RuntimeError("speech failed")),
                patch.object(swap, "Thread"),
                patch.object(swap.time, "sleep"),
                patch.object(swap.backends, "listening", return_value=False),
                patch.object(swap.launch_util, "kill_process_tree") as kill,
                self.assertRaisesRegex(RuntimeError, "speech failed"),
            ):
                probe.run(1)
            kill.assert_called_once_with(123)
            self.assertEqual(probe.report["status"], "failed")
            self.assertTrue(probe.stop.is_set())


if __name__ == "__main__":
    unittest.main()
