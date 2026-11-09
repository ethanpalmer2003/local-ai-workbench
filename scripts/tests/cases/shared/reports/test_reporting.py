import csv
import json
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from scripts.benchmarks.shared.reporting import report_run
from scripts.tests.shared.paths import CasePaths, Outcome, RunPaths
from scripts.tests.shared.timing import timed


class Reporting(unittest.TestCase):
    def test_partial_results_preserve_settings_and_flat_csv(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with (
                self.assertRaisesRegex(RuntimeError, "second clip failed"),
                report_run(output, "fixture", "model-free", settings={"repeat": 2}) as report,
            ):
                report.results.append({"seconds": 12.5, "settings": {"tile": 64}, "outputs": ["clip.mp4"]})
                raise RuntimeError("second clip failed")
            payload = json.loads((output.artifacts / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["settings"], {"repeat": 2})
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["error"], "second clip failed")
            self.assertEqual(len(payload["results"]), 1)
            with (output.artifacts / "results.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["settings.tile"], "64")
            self.assertEqual(json.loads(rows[0]["outputs"]), ["clip.mp4"])

    def test_run_layout_groups_outcome_and_preserves_internal_folders(self):
        with CasePaths(__file__).temporary_directory() as folder:
            with patch.object(CasePaths, "output", new_callable=PropertyMock, return_value=Path(folder)):
                default = CasePaths(__file__).new_run()
                reviewed = CasePaths(__file__).new_run(Outcome.NO_GAIN)
            self.assertEqual(default.root.parent.name, "unreviewed")
            self.assertEqual(reviewed.root.parent.name, "no-gain")
            self.assertTrue(all(path.is_dir() for path in (reviewed.logs, reviewed.artifacts, reviewed.temp)))

    def test_failed_and_completed_runs_write_matching_reports(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with self.assertRaisesRegex(RuntimeError, "fixture"), report_run(output, "fixture", "model-free"):
                raise RuntimeError("fixture")
            payload = json.loads((output.artifacts / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertGreaterEqual(payload["total_seconds"], 0)
            self.assertIn("Status: failed", (output.artifacts / "report.md").read_text(encoding="utf-8"))
            with report_run(output, "fixture", "model-free", reasoning="medium"):
                pass
            self.assertEqual(json.loads((output.artifacts / "report.json").read_text())["reasoning"], "medium")
            self.assertIn("Reasoning: medium", (output.artifacts / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((output.artifacts / "report.json").read_text())["status"], "completed")

    def test_interruption_is_preserved_and_propagated(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with self.assertRaises(KeyboardInterrupt), report_run(output, "fixture", "model-free"):
                raise KeyboardInterrupt
            payload = json.loads((output.artifacts / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "interrupted")

    def test_successful_cli_exit_is_not_a_failure(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with self.assertRaises(SystemExit), report_run(output, "fixture", "model-free"):
                raise SystemExit(0)
            payload = json.loads((output.artifacts / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")

    def test_a_report_without_a_recorded_identity_stays_unprovenanced(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with report_run(output, "fixture", "model-free"):
                pass
            payload = json.loads((output.artifacts / "report.json").read_text(encoding="utf-8"))
            self.assertNotIn("provenance", payload)

    def test_a_recorded_identity_reaches_the_report(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with report_run(output, "fixture", "model-free") as report:
                report.provenance = {"subject": "fixture", "models": [], "frameworks": []}
            payload = json.loads((output.artifacts / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["provenance"]["subject"], "fixture")


if __name__ == "__main__":
    with timed("shared/test_reporting"):
        unittest.main()
