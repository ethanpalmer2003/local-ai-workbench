"""Server comparison request parsing and report math; no server is started."""

import unittest
from unittest.mock import patch

from scripts.benchmarks.shared import framework_compare as compare


class FakeResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exception: object) -> bool:
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self) -> list[bytes]:
        return self.lines


class FrameworkCompareTests(unittest.TestCase):
    def test_delta_parsing_skips_keepalives_and_the_terminator(self):
        self.assertIsNone(compare._delta_text(b""))
        self.assertIsNone(compare._delta_text(b"data: [DONE]"))
        self.assertIsNone(compare._delta_text(b'data: {"choices":[{"delta":{}}]}'))
        self.assertEqual(compare._delta_text(b'data: {"choices":[{"delta":{"content":"hi"}}]}'), "hi")

    def test_stream_chat_counts_content_chunks_after_the_role_delta(self):
        lines = [
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            b'data: {"choices":[{"delta":{"content":"a"}}]}',
            b'data: {"choices":[{"delta":{"content":"b"}}]}',
            b"data: [DONE]",
        ]
        served = compare.Served("http://127.0.0.1:1", "model", 1)
        with patch.object(compare.requests, "post", return_value=FakeResponse(lines)) as post:
            row = compare.stream_chat(served, "hello", 8)
        self.assertEqual(row["chunks"], 2)
        self.assertIsNotNone(row["first_token_seconds"])
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 8)
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:1/v1/chat/completions")

    def test_summary_means_the_measured_requests_and_marks_empty_backends(self):
        rows = compare.summarize(
            [
                {
                    "backend": "lemonade",
                    "model": "m.gguf",
                    "load_seconds": 1.0,
                    "requests": [
                        {"chunks": 8, "first_token_seconds": 0.5, "chunks_per_second": 4.0},
                        {"chunks": 6, "first_token_seconds": 0.7, "chunks_per_second": 3.0},
                    ],
                },
                {"backend": "koboldcpp", "model": "m.gguf", "load_seconds": 2.0, "requests": []},
            ]
        )
        self.assertIn("| lemonade | m.gguf | 1.0 | 0.60 | 3.50 |", rows)
        self.assertIn("| koboldcpp | m.gguf | 2.0 | n/a | n/a |", rows)


if __name__ == "__main__":
    unittest.main()
