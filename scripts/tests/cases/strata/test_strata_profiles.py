"""Strata screening guards, streamed accounting and fixed-answer grading without inference."""

import io
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.benchmarks.coding_agents import strata_profiles as screen
from scripts.benchmarks.coding_agents.shared import benchmark_requests
from scripts.launchers.strata.strata_pi import StrataConnection
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.process_fixtures import running_process


class StrataProfileTests(unittest.TestCase):
    def test_expression_grading_rejects_malformed_missing_and_extra_results(self):
        self.assertTrue(screen.grade("```json\n" + json.dumps(screen.EXPECTED) + "\n```")["exact"])
        for value in ("explanation", "[]", json.dumps(screen.EXPECTED + [0])):
            self.assertEqual(screen.grade(value)["passed"], 0)

    def test_low_ram_guard_only_stops_the_owned_process(self):
        process = running_process(pid=123)
        with CasePaths(__file__).temporary_directory() as folder:
            guard = screen.MemoryGuard(process, time.monotonic() + 60, 3, Path(folder) / "ram.jsonl")
            with (
                patch("psutil.virtual_memory", return_value=SimpleNamespace(available=2**30, percent=96)),
                patch.object(screen.launch_util, "kill_process_tree") as stop,
            ):
                guard.run()
            stop.assert_called_once_with(123)
            assert guard.reason is not None
            self.assertIn("RAM", guard.reason)

    def test_streamed_request_preserves_native_usage_and_first_token_time(self):
        chunks = [
            {"choices": [{"delta": {"content": "ok"}}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
                "timings": {"predicted_per_second": 35},
            },
        ]
        response = io.BytesIO(
            b"".join(b"data: " + json.dumps(row).encode() + b"\n\n" for row in chunks) + b"data: [DONE]\n"
        )
        connection = StrataConnection(Path("unused"), {"model_name": "swift"}, 1, "test-key")
        with patch.object(benchmark_requests.urllib.request, "urlopen", return_value=response):
            record = screen.request(connection, "prompt", 128, time.monotonic() + 60)
        self.assertEqual(record["content"], "ok")
        self.assertTrue(record["accounting"]["usage_complete"])
        self.assertEqual(record["accounting"]["total_tokens"], 11)
        self.assertEqual(record["native_timings"]["predicted_per_second"], 35)
        self.assertIsNotNone(record["first_token_seconds"])
        self.assertNotIn("test-key", json.dumps(record))
