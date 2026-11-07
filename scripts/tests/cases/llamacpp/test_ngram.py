import ast
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.benchmarks.llamacpp import benchmark_ngram as benchmark
from scripts.benchmarks.llamacpp import benchmark_speedbench, trial
from scripts.benchmarks.shared.reporting import context_category
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.process_fixtures import running_process


class NgramWorkloads(unittest.TestCase):
    def test_speedbench_retains_completed_round_when_next_round_is_interrupted(self):
        @dataclass
        class Sample:
            category: str = "coding"

        @dataclass
        class Result:
            ok: bool = True
            latency_s: float = 1
            predicted_per_second: float = 20
            prompt_tokens: int = 10

        with CasePaths(__file__).temporary_directory() as folder:
            output = RunPaths(Path(folder))
            output.create()
            conf = Mock(port=9931, alias="test", build_dir=Path(folder), model=Path(folder) / "unused.gguf")
            from scripts.launchers.llamacpp.llamacpp_profiles import SWIFT15_BASE

            conf.profile = SWIFT15_BASE
            conf.build_cmd.return_value = ["unused"]
            runner = Mock(side_effect=[Result(), Result(), KeyboardInterrupt()])
            with (
                patch.object(sys, "argv", ["benchmark", "--rounds", "2"]),
                patch.object(trial.launch_util, "llama_server_running", return_value=False),
                patch.object(trial.launch_util, "port_listening", return_value=False),
                patch.object(trial.launch_util, "kill_process_tree"),
                patch.object(
                    trial.launch_util,
                    "launch_process",
                    side_effect=lambda *args, **kwargs: running_process(pid=12345),
                ),
                patch.object(benchmark_speedbench, "LlamaConfig", return_value=conf),
                patch.object(trial, "LlamaConfig", return_value=conf),
                patch.object(benchmark_speedbench, "BenchmarkPaths") as paths,
                patch.object(trial, "wait_ready"),
                patch.object(benchmark_speedbench, "post_json"),
                patch.object(
                    benchmark_speedbench.runpy,
                    "run_path",
                    return_value={"load_samples": lambda _: [Sample()], "run_one": runner},
                ),
                patch.dict(benchmark_speedbench.os.environ),
                self.assertRaises(KeyboardInterrupt),
            ):
                paths.return_value.new_run.return_value = output
                benchmark_speedbench.main()
            evidence = json.loads((output.artifacts / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(len(evidence["rounds"]), 1)
            report = json.loads((output.artifacts / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "interrupted")

    def test_rewrite_grading_rejects_extra_functions_and_wrong_edits(self):
        source = benchmark.source_block(9000)
        expected = source.replace("negative amount", "invalid amount")
        self.assertTrue(benchmark.rewrite_correct(expected, expected))
        self.assertFalse(benchmark.rewrite_correct(source, expected))
        self.assertFalse(benchmark.rewrite_correct(expected + benchmark.source_block(9001), expected))
        self.assertFalse(benchmark.rewrite_correct("not python !", expected))
        self.assertIsInstance(ast.parse(expected), ast.Module)

    def test_context_labels_use_actual_depth(self):
        self.assertEqual(context_category(15), "low-context")
        self.assertEqual(context_category(4096), "medium-context")
        self.assertEqual(context_category(16497), "medium-context")
        self.assertEqual(context_category(32768), "high-context")

    def test_reference_context_is_token_sized_without_launching(self):
        with patch.object(
            benchmark, "post_json", side_effect=[{"tokens": list(range(200))}, {"content": "code"}]
        ) as post:
            rows = benchmark.workloads("http://unused", benchmark.Settings(context_tokens=100), 0)
        self.assertEqual(post.call_args_list[1].args[1], {"tokens": list(range(100))})
        self.assertEqual(rows[1].requested_depth, 100)
        self.assertIn("invalid amount", rows[1].expected or "")
        self.assertNotEqual(rows[0].prompt, rows[1].prompt)


if __name__ == "__main__":
    unittest.main()
