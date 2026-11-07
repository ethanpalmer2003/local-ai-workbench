"""Paired benchmark order, checkpoints and quality/usage report semantics."""

import argparse
import json
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.launchers import launcher_config as cfg
from scripts.benchmarks.coding_agents.shared import benchmark_agents as benchmark
from scripts.benchmarks.coding_agents.shared.benchmark_backends import BenchmarkEndpoint
from scripts.benchmarks.coding_agents.shared.benchmark_backends import benchmark_llama_config
from scripts.benchmarks.coding_agents.shared.framework_tasks import TASKS
from scripts.tests.shared.paths import CasePaths, RunPaths


class BenchmarkMatrixTests(unittest.TestCase):
    def test_backend_and_harness_orders_rotate_without_losing_checkpoints(self):
        starts = []
        trials = []
        args = argparse.Namespace(
            temperature=0,
            thinking="low",
            reasoning_budget=2048,
            seed=42,
            backends=["llamacpp", "strata"],
            clients=["pi", "ohmypi"],
            repeats=2,
            strata_config=None,
            max_output_tokens=4096,
            context_size=32768,
            timeout=60,
            max_turns=12,
        )

        @contextmanager
        def endpoint(name, _conf, _output, _config):
            starts.append(name)
            yield BenchmarkEndpoint(
                name, name + "-model", "http://127.0.0.1:18501/v1", "secret", metadata={"startup_seconds": 0}
            )

        def trial(client, task, repeat, output, conf, timeout, turns, relay, pi_extensions=False):
            trials.append((relay.endpoint.backend, client, repeat))
            return benchmark.Result(
                client,
                task.name,
                repeat,
                True,
                1,
                0,
                False,
                "workspace",
                True,
                turns,
                backend=relay.endpoint.backend,
                model=relay.endpoint.model,
            )

        def relay(endpoint, _settings, **_kwargs):
            manager = MagicMock()
            manager.__enter__.return_value.endpoint = endpoint
            return manager

        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(benchmark, "preflight"),
            patch.object(benchmark, "backend_endpoint", side_effect=endpoint),
            patch.object(benchmark, "BenchmarkVram"),
            patch.object(benchmark, "warmup", return_value={}),
            patch.object(benchmark, "endpoint_identity", return_value="mock-process:model"),
            patch.object(benchmark, "BenchmarkRelay", side_effect=relay),
            patch.object(benchmark.launch_util, "listening_process_ids", return_value=[]),
            patch.object(benchmark, "run_task", side_effect=trial),
            patch.object(benchmark, "save_results") as save,
        ):
            output = RunPaths(Path(folder))
            output.create()
            results = benchmark.run_matrix(args, [TASKS[0]], benchmark_llama_config({}), output, {})
        self.assertEqual(starts, ["llamacpp", "strata", "strata", "llamacpp"])
        self.assertEqual(len(results), 8)
        self.assertEqual(trials[:2], [("llamacpp", "pi", 1), ("llamacpp", "ohmypi", 1)])
        self.assertEqual(trials[4:6], [("strata", "ohmypi", 2), ("strata", "pi", 2)])
        self.assertEqual(save.call_count, 9)

    def test_strata_report_does_not_claim_a_llama_build_or_zero_missing_tokens(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            package = root / "pi" / "package.json"
            package.parent.mkdir()
            package.write_text('{"version":"test-version"}', encoding="utf-8")
            client = replace(cfg.PI_CLIENT, entry=package.parent / "dist" / "cli.js")
            result = benchmark.Result(
                "pi", "proverb", 1, False, 3, 1, False, "workspace", True, 12, backend="strata", model="big-swift"
            )
            with patch.object(cfg, "PI_CLIENT", client):
                benchmark.save_results(root, [result], benchmark_llama_config({}))
            data = json.loads((root / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(data["model"], "big-swift")
            self.assertIsNone(data["configured_build"])
            self.assertTrue(data["results"][0]["tests_passed"])
            self.assertFalse(data["results"][0]["passed"])
            self.assertIsNone(data["results"][0]["total_tokens"])
            pi = data["client_configuration"]["pi"]
            self.assertFalse(pi["pi_extensions"])
            self.assertEqual(pi["packages"], [])
            self.assertIn("--no-extensions", pi["cli_args"])
            self.assertTrue(any(row["path"].endswith("turn_budget.mjs") for row in pi["local_extensions"]))
            self.assertTrue(all(row["sha256"] for row in pi["local_extensions"]))
            summary = json.loads((root / "summary.json").read_text())
            self.assertEqual(summary["client_configuration"], data["client_configuration"])
            self.assertIn("unavailable/incomplete", (root / "comparison.md").read_text())


if __name__ == "__main__":
    unittest.main()
