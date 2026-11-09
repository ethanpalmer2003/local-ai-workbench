"""Generic stage runner: progress parsing, skip detection and the slow marks."""

import io
import queue
import unittest

from scripts.tools import stage_runner


class StageRunnerTests(unittest.TestCase):
    def test_progress_lines_report_target_counts(self) -> None:
        self.assertEqual(stage_runner.parse_progress("[PROGRESS] launchers [##--] 2/6 kobold"), (2, 6, "kobold"))
        self.assertEqual(stage_runner.parse_progress("[PROGRESS] backends [####----] 4/8 gemma"), (4, 8, "gemma"))
        self.assertIsNone(stage_runner.parse_progress("[TIME] kobold: 16.580s"))

    def test_skip_lines_name_their_stage(self) -> None:
        self.assertEqual(stage_runner.skipped("[SKIP] launchers: sources unchanged"), "launchers")
        self.assertEqual(stage_runner.skipped("[SKIP] backends: sources unchanged"), "backends")
        self.assertEqual(stage_runner.skipped("[SKIP] kobold: target not installed"), "kobold")
        self.assertIsNone(stage_runner.skipped("[TIME] kobold: 16.580s"))

    def test_carriage_return_updates_arrive_as_separate_lines(self) -> None:
        lines: queue.Queue[str | None] = queue.Queue()
        stage_runner._reader(io.StringIO("check 1/3\rcheck 2/3\rcheck 3/3\r"), lines)
        seen = []
        while (line := lines.get_nowait()) is not None:
            seen.append(line)
        self.assertEqual(seen, ["check 1/3", "check 2/3", "check 3/3"])

    def test_slow_and_failed_stages_are_marked(self) -> None:
        stage = stage_runner.Stage("gate", "scripts.review", typical=55, high=80)
        self.assertEqual(stage_runner._mark(stage_runner.Result("gate", "ok", 95.0), stage), "SLOW")
        self.assertEqual(stage_runner._mark(stage_runner.Result("gate", "ok", 54.0), stage), "OK")
        self.assertEqual(stage_runner._mark(stage_runner.Result("gate", "failed", 3.0), stage), "FAIL")
        self.assertEqual(stage_runner._mark(stage_runner.Result("gate", "skipped", 0.1), stage), "SKIP")

    def test_describe_reports_the_outcome(self) -> None:
        stage = stage_runner.Stage("gate", "scripts.review", typical=55, high=80)
        self.assertIn("[WARN]", stage_runner._describe(stage_runner.Result("gate", "ok", 95.0), stage))
        self.assertIn("[OK]", stage_runner._describe(stage_runner.Result("gate", "ok", 54.0), stage))
        self.assertIn("[SKIP]", stage_runner._describe(stage_runner.Result("gate", "skipped", 0.1), stage))

    def test_an_empty_plan_runs_nothing(self) -> None:
        self.assertEqual(stage_runner.run(()), [])

    def test_the_one_stage_cli_keeps_child_arguments(self) -> None:
        stage = stage_runner._stage_from_argv(["pkg.module", "--update", "--stage-known", "gate"])
        self.assertEqual(stage.key, "gate")
        self.assertEqual(stage.module, "pkg.module")
        self.assertEqual(stage.typical, 55)
        self.assertEqual(stage.high, 80)
        self.assertEqual(stage.arguments, ("--update",))

    def test_the_one_stage_cli_accepts_explicit_bounds_and_title(self) -> None:
        stage = stage_runner._stage_from_argv(
            ["pkg.module", "--stage-title", "build", "--stage-typical", "90", "--stage-high", "600", "--check"]
        )
        self.assertEqual((stage.key, stage.typical, stage.high, stage.arguments), ("build", 90.0, 600.0, ("--check",)))

    def test_the_one_stage_cli_needs_a_module(self) -> None:
        with self.assertRaises(SystemExit):
            stage_runner._stage_from_argv([])
