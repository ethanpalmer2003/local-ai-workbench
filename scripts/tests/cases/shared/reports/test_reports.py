import csv
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks import amalgamate_benchmarks as summaries
from scripts.benchmarks.llamacpp import benchmark_llamacpp_profiles as benchmark
from scripts.shared.timing import timed
from scripts.tests.shared.paths import CasePaths, RunPaths


class ReportOutputs(unittest.TestCase):
    def test_overthink_keeps_each_profiles_transcript(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with (
                patch.object(benchmark, "output", output),
                patch.object(benchmark.launch_util, "launch_process"),
                patch.object(benchmark, "await_http"),
                patch.object(benchmark, "stop_server"),
                patch.object(benchmark, "post_json", return_value={"choices": [{"message": {"content": "answer"}}]}),
            ):
                for profile in ("swift15", "swift15-mtp-notemplate"):
                    benchmark.overthink_profile(profile, {"code": "prompt"}, 1, 1)
            self.assertEqual(len(list((output.artifacts / "overthink").glob("*.json"))), 2)

    def test_decode_measurement_requires_native_timings(self):
        with patch.object(benchmark, "post_json", return_value={"timings": {"predicted_n": 20, "predicted_ms": 500}}):
            self.assertEqual(benchmark.completion_request("unused", "prompt", 20, 1).tokens_per_second, 40)
        with patch.object(benchmark, "post_json", return_value={"tokens_predicted": 20}), self.assertRaises(KeyError):
            benchmark.completion_request("unused", "prompt", 20, 1)

    def test_benchmark_does_not_replace_an_existing_server(self):
        with (
            patch.object(sys, "argv", ["benchmark"]),
            patch.object(benchmark.launch_util, "llama_server_running", return_value=True),
            patch.object(benchmark, "run_profile") as run,
            self.assertRaisesRegex(RuntimeError, "Stop the existing llama-server"),
        ):
            benchmark.main()
        run.assert_not_called()

    def test_benchmark_failure_preserves_report_and_fails_the_command(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with (
                patch.object(sys, "argv", ["benchmark", "--profiles", "swift15"]),
                patch.object(benchmark.launch_util, "llama_server_running", return_value=False),
                patch.object(benchmark, "BenchmarkPaths") as paths,
                patch.object(benchmark, "run_profile", side_effect=RuntimeError("server rejected options")),
                patch.object(benchmark, "output", output),
            ):
                paths.return_value.new_run.return_value = output
                with self.assertRaisesRegex(RuntimeError, "Profile benchmark failed"):
                    benchmark.main()
            report = next(output.artifacts.glob("llama-benchmark-summary-*.txt"))
            self.assertIn("server rejected options", report.read_text(encoding="utf-8"))

    def test_benchmark_defaults_reference_current_profiles_and_write_reports(self):
        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            with (
                patch.object(sys, "argv", ["benchmark"]),
                patch.object(benchmark.launch_util, "llama_server_running", return_value=False),
                patch.object(benchmark, "BenchmarkPaths") as paths,
                patch.object(
                    benchmark,
                    "run_profile",
                    return_value=(
                        {"code": [benchmark.Sample(16, 1.0, 16.0, 32, 0.4, 0)]},
                        {"code": benchmark.Sample(32, 1.0, 16.0, 32, 0.4, 0)},
                        {
                            "resident": {},
                            "peak_process_used_mb": None,
                            "peak_total_used_mb": None,
                            "prefill_samples": {"code": benchmark.Sample(32, 1.0, 16.0, 32, 0.4, 0)},
                        },
                    ),
                ) as run,
                patch.object(benchmark, "output", output),
            ):
                paths.return_value.new_run.return_value = output
                benchmark.main()
            profiles = {**benchmark.LLAMACPP_PROFILES, **benchmark.LLAMACPP_BENCHMARK_PROFILES}
            self.assertTrue(all(call.args[0] in profiles for call in run.call_args_list))
            self.assertEqual([call.args[0] for call in run.call_args_list], ["swift15", "swift15-mtp-notemplate"])
            self.assertEqual(len(list(output.artifacts.glob("*.csv"))), 1)
            self.assertEqual(len(list(output.artifacts.glob("llama-benchmark-summary-*.txt"))), 1)

    def test_summary_collection_reads_nested_legacy_and_current_formats(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            source = root / "input" / "legacy" / "artifacts" / "summaries"
            source.mkdir(parents=True)
            (source / "llama-benchmark-summary-old.txt").write_text(
                "profile\tprompt\ttokens\tavg_seconds\ttokens_per_second\nswift15\tcode\t12\t3\t4\n", encoding="utf-8"
            )
            (source / "llama-benchmark-summary-new.txt").write_text(
                "build/profile\tprompt\ttokens\tctx_depth\tavg_s\ttok/s\nlemonade/swift15\tprose\t20\t1024\t2\t10\n",
                encoding="utf-8",
            )
            output = RunPaths(root / "output")
            output.create()
            with (
                patch.object(summaries, "SOURCE_DIRS", (root / "input",)),
                patch.object(summaries, "BenchmarkPaths") as paths,
            ):
                paths.return_value.new_run.return_value = output
                rows = summaries.collect_rows()
                csv_file, table_file = summaries.write_outputs(rows)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row.model == "" and row.params == "" for row in rows))
            self.assertEqual({row.tok_s for row in rows}, {"4", "10"})
            self.assertEqual(csv_file.parent, output.artifacts)
            self.assertIn("10.0", table_file.read_text(encoding="utf-8"))

    def test_summary_uses_recorded_configuration_instead_of_current_defaults(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            summary = root / "llama-benchmark-summary-run.txt"
            summary.write_text("unused when the recorded CSV exists", encoding="utf-8")
            row = summaries.Row(
                "then",
                "lemonade",
                "swift15",
                "original.gguf",
                "original.ini",
                "draft=4",
                "code",
                "20",
                "1024",
                "2",
                "10",
            )
            with (root / "llama-benchmark-csv-run.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row.__dict__))
                writer.writeheader()
                writer.writerow(row.__dict__)
            self.assertEqual(summaries.parse_summary(summary), [row])


if __name__ == "__main__":
    with timed("shared/test_reports"):
        unittest.main()
