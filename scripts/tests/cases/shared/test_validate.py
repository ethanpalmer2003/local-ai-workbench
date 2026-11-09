"""Full validation runner: stage plan, expected ranges and child progress parsing."""

import contextlib
import io
import unittest
from unittest.mock import patch

from scripts.tests import validate
from scripts.tests.shared import stage_times


class ValidatePlanTests(unittest.TestCase):
    def test_every_stage_has_a_low_typical_and_high_range(self) -> None:
        for stage in validate.STAGES:
            low, typical, high = stage_times.RANGES[stage.key]
            self.assertLess(low, typical)
            self.assertLess(typical, high)

    def test_stage_keys_are_unique_and_ordered(self) -> None:
        keys = [stage.key for stage in validate.STAGES]
        self.assertEqual(keys, ["gate", "suite", "launchers", "backends"])

    def test_plan_narrows_by_key(self) -> None:
        self.assertEqual([stage.key for stage in validate.plan(["suite"])], ["suite"])
        self.assertEqual(len(validate.plan()), len(validate.STAGES))

    def test_classify_flags_only_a_stage_above_its_high(self) -> None:
        _, _, high = stage_times.RANGES["gate"]
        self.assertEqual(stage_times.classify("gate", high), "ok")
        self.assertEqual(stage_times.classify("gate", high + 1), "slow")

    def test_progress_lines_report_target_counts(self) -> None:
        self.assertEqual(validate.parse_progress("[PROGRESS] launchers [##--] 2/6 kobold"), (2, 6, "kobold"))
        self.assertEqual(validate.parse_progress("[PROGRESS] backends [####----] 4/8 gemma"), (4, 8, "gemma"))
        self.assertIsNone(validate.parse_progress("[TIME] kobold: 16.580s"))

    def test_skip_lines_are_recognized(self) -> None:
        self.assertTrue(validate.skipped("[SKIP] launchers: sources unchanged since the last pass (a, b)"))
        self.assertTrue(validate.skipped("[SKIP] backends: sources unchanged since the last pass"))
        self.assertFalse(validate.skipped("[SKIP] kobold: target not installed"))

    def test_describe_reports_slow_and_skipped_stages(self) -> None:
        self.assertIn("[WARN]", validate._describe(validate.Result("gate", "ok", 10_000.0)))
        self.assertIn("[SKIP]", validate._describe(validate.Result("launchers", "skipped", 0.1)))

    def test_dry_run_prints_the_plan_and_spawns_nothing(self) -> None:
        output = io.StringIO()
        with (
            patch.object(validate.subprocess, "Popen", side_effect=AssertionError("no child")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(validate.main(["--dry-run"]), 0)
        self.assertIn("launchers", output.getvalue())
