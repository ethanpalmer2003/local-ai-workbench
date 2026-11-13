"""Coding-engine benchmark: one contract for prefill, decode and prompt reuse."""

import argparse
import unittest
from typing import Any

from scripts.benchmarks.inference_engines import benchmark_coding_engines as benchmark


def row(prompt_n: int, prompt_ms: float, predicted_n: int, predicted_ms: float, ttft: float = 1.0) -> dict[str, Any]:
    return {
        "finished": True,
        "seconds": ttft + predicted_ms / 1000,
        "first_token_seconds": ttft,
        "usage": {"prompt_tokens": prompt_n, "completion_tokens": predicted_n, "total_tokens": prompt_n + predicted_n},
        "native_timings": {
            "prompt_n": prompt_n,
            "prompt_ms": prompt_ms,
            "predicted_n": predicted_n,
            "predicted_ms": predicted_ms,
            "draft_n": 100,
            "draft_n_accepted": 50,
        },
    }


def namespace(**values: Any) -> argparse.Namespace:
    return argparse.Namespace(**values)


class CodingEngineSummaryTests(unittest.TestCase):
    def test_cold_prefill_is_separate_from_the_warm_median(self) -> None:
        rows = {
            "cold": {"a": row(1000, 2000.0, 8, 100.0), "b": row(1000, 2000.0, 8, 100.0)},
            "warm": {"a": [row(1000, 1000.0, 128, 2560.0, 0.4)], "b": [row(1000, 1000.0, 128, 2560.0, 0.4)]},
        }
        summary = benchmark.summarize(rows)
        self.assertEqual(summary["cold_prefill_tokens_per_second"], 500.0)
        self.assertEqual(summary["decode_tokens_per_second"], 50.0)
        self.assertEqual(summary["ttft_seconds"], 0.4)
        self.assertEqual(summary["draft_acceptance"], 0.5)
        self.assertEqual(summary["prompt_tokens"], 1000)
        self.assertEqual(summary["tasks"], 2)
        self.assertEqual(summary["samples"], 2)
        # - a warm sample prefills only its cache miss, so it cannot be reported as a rate
        self.assertNotIn("warm_prefill_tokens_per_second", summary)

    def test_a_task_reports_its_median_and_range(self) -> None:
        rows = {
            "cold": {"a": row(1000, 2000.0, 8, 100.0)},
            "warm": {
                "a": [
                    row(1000, 1000.0, 128, 6400.0, 0.4),
                    row(1000, 1000.0, 128, 2560.0, 0.4),
                    row(1000, 1000.0, 128, 3200.0, 0.4),
                ]
            },
        }
        summary = benchmark.summarize(rows)
        self.assertEqual(
            summary["per_task"]["a"],
            {"decode_median": 40.0, "decode_min": 20.0, "decode_max": 50.0, "ttft_median": 0.4},
        )
        self.assertEqual(summary["decode_tokens_per_second"], 40.0)
        self.assertEqual(summary["decode_range"], (20.0, 50.0))

    def test_a_request_record_keeps_timings_and_drops_the_stream(self) -> None:
        record = benchmark.request_record({**row(10, 5.0, 4, 8.0), "content": "x" * 500})
        self.assertEqual(record["native_timings"]["prompt_n"], 10)
        self.assertEqual(record["native_timings"]["draft_n_accepted"], 50)
        self.assertNotIn("content", record)

    def test_context_is_prepended_only_when_given(self) -> None:
        with_context = benchmark.conversation("task", "ctx")
        self.assertIn("ctx\n\ntask", with_context[-1]["content"])
        self.assertEqual(benchmark.conversation("task", "")[-1]["content"], "task")

    def test_an_endpoint_gains_the_v1_suffix_once(self) -> None:
        plain = benchmark.endpoint_session(namespace(endpoint="http://127.0.0.1:8080", api_key="key", model="swift"))
        self.assertEqual(plain.connection.base_url, "http://127.0.0.1:8080/v1")
        with_v1 = benchmark.endpoint_session(namespace(endpoint="http://127.0.0.1:8080/v1", api_key="", model=""))
        self.assertEqual(with_v1.connection.base_url, "http://127.0.0.1:8080/v1")


if __name__ == "__main__":
    unittest.main()
