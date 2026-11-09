"""Full validation runner: the stage plan, the framework preflight and the dry run."""

import contextlib
import io
import unittest
from unittest.mock import patch

from scripts.tests import validate
from scripts.tests.shared import stage_times

DEFAULT = ["frameworks", "gate", "suite", "launchers", "backends"]


class ValidatePlanTests(unittest.TestCase):
    def test_every_stage_has_a_low_typical_and_high_range(self) -> None:
        for stage in validate.plan():
            low, typical, high = stage_times.RANGES[stage.key]
            self.assertLess(low, typical)
            self.assertLess(typical, high)

    def test_frameworks_update_runs_before_the_checks(self) -> None:
        self.assertEqual([stage.key for stage in validate.plan()], DEFAULT)
        self.assertEqual(validate.plan()[0].module, "scripts.download.frameworks.update_frameworks")
        self.assertIn("--skip-comfyui", validate.plan()[0].arguments)

    def test_the_model_check_is_opt_in(self) -> None:
        self.assertNotIn("models", [stage.key for stage in validate.plan()])
        keys = [stage.key for stage in validate.plan(models=True)]
        self.assertEqual(keys, ["frameworks", "models", "gate", "suite", "launchers", "backends"])

    def test_plan_narrows_by_key(self) -> None:
        self.assertEqual([stage.key for stage in validate.plan(["suite"])], ["suite"])
        self.assertEqual(len(validate.plan(DEFAULT)), len(DEFAULT))

    def test_dry_run_prints_the_plan_and_spawns_nothing(self) -> None:
        output = io.StringIO()
        with (
            patch.object(validate.stage_runner.subprocess, "Popen", side_effect=AssertionError("no child")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(validate.main(["--dry-run", "--models"]), 0)
        self.assertIn("frameworks", output.getvalue())
        self.assertIn("models", output.getvalue())
        self.assertIn("backends", output.getvalue())

    def test_no_update_drops_the_framework_preflight(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(validate.main(["--dry-run", "--no-update"]), 0)
        self.assertNotIn("\n  frameworks", output.getvalue())
