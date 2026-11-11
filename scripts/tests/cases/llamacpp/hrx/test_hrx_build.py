"""Build-step subprocess failures and cancellation must not leave owned processes running."""

import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.download.frameworks.llamacpp.hrx import build as build_hrx
from scripts.tests.cases.llamacpp.hrx import hrx_update_validation
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.process_fixtures import exited_process


class HrxBuildTests(unittest.TestCase):
    def test_failed_installed_validation_restores_previous_runtime(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "runtime.dll").write_bytes(b"old")
            previous = {
                "checkpoint": str(root / "previous"),
                "sha256": {"runtime.dll": hashlib.sha256(b"old").hexdigest()},
            }
            (runtime / "checkpoint.json").write_text(json.dumps(previous), encoding="utf-8")
            paths = RunPaths(root / "unreviewed/run")
            paths.create()
            (paths.temp / "bin").mkdir()
            (paths.temp / "bin/runtime.dll").write_bytes(b"new")
            checks = {"hashes": {"runtime.dll": hashlib.sha256(b"new").hexdigest()}}
            with (
                patch.dict(build_hrx.cfg.LLAMACPP_BUILDS, {"hrx": SimpleNamespace(bin_dir=runtime)}),
                patch.object(build_hrx.prepare_hrx, "CHECKPOINT_POINTER", root / "latest.json"),
                patch.object(build_hrx.launch_util, "llama_server_running", return_value=False),
                patch.object(hrx_update_validation, "verify_candidate_evidence", return_value=checks),
                patch.object(hrx_update_validation, "record_sources"),
                patch.object(build_hrx, "run_step", side_effect=RuntimeError("installed validation failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "installed validation failed"):
                    build_hrx.install_candidate(paths)
                self.assertEqual((runtime / "runtime.dll").read_bytes(), b"old")
                self.assertEqual(json.loads((runtime / "checkpoint.json").read_text(encoding="utf-8")), previous)

    @fixture_processes()
    def test_failed_step_retains_output_and_reports_log(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(build_hrx.launch_util, "assign_process_to_job"),
        ):
            paths = RunPaths(Path(folder))
            paths.create()
            with self.assertRaisesRegex(RuntimeError, "native-check failed \\(7\\)"):
                build_hrx.run_step(
                    "native-check", [sys.executable, "-c", "print('compiler diagnostic'); exit(7)"], paths
                )
            self.assertIn("compiler diagnostic", (paths.logs / "native-check.log").read_text(encoding="utf-8"))

    def test_cancelled_step_stops_owned_process_tree(self):
        process = exited_process(pid=123)
        process.wait.side_effect = [KeyboardInterrupt(), 0]
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(build_hrx.subprocess, "Popen", return_value=process),
            patch.object(build_hrx.launch_util, "assign_process_to_job"),
            patch.object(build_hrx.launch_util, "kill_process_tree") as kill,
        ):
            paths = RunPaths(Path(folder))
            paths.create()
            with self.assertRaises(KeyboardInterrupt):
                build_hrx.run_step("canceled", ["unused"], paths)
            kill.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
