"""Context stream benchmark: the token trace counts output tokens, not prompt progress."""

import io
import json
import time
import unittest
from types import SimpleNamespace

from scripts.benchmarks.llamacpp import benchmark_context_stream as stream


def line(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode() + b"\n"


class ContextStreamTests(unittest.TestCase):
    def test_prompt_progress_is_not_counted_as_an_output_token(self):
        events = [
            line({"content": "", "tokens": [0], "prompt_progress": {"total": 26, "processed": 0}}),
            line({"content": "", "tokens": [0], "prompt_progress": {"total": 26, "processed": 22}}),
            line({"content": "The", "tokens": [123], "tokens_predicted": 1}),
            line({"content": " answer", "tokens": [456], "tokens_predicted": 2}),
            line({"content": ",", "tokens": [789], "tokens_predicted": 3}),
            line({"stop": True, "tokens": [], "timings": {"predicted_n": 3}}),
        ]
        args = SimpleNamespace(request_timeout=30.0)
        count, traced, content, final = stream._consume_stream(
            io.BytesIO(b"".join(events)), io.StringIO(), args, time.perf_counter() + 30, time.perf_counter()
        )
        self.assertEqual(count, 3)
        self.assertEqual([event["tokens"] for event in traced], [1, 2, 3])
        self.assertEqual("".join(content), "The answer,")
        self.assertEqual(final["timings"]["predicted_n"], 3)

    def test_windows_are_built_from_the_streamed_token_marks(self):
        traced = [{"tokens": 1, "seconds": 0.1}, {"tokens": 2, "seconds": 0.2}, {"tokens": 3, "seconds": 0.5}]
        windows = stream.token_windows(traced, 2)
        self.assertTrue(windows)
        self.assertEqual((windows[-1]["start_token"], windows[-1]["end_token"]), (1, 3))


if __name__ == "__main__":
    unittest.main()
