"""Usage accounting and streaming relay regressions; no model or GPU required."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler

from scripts.benchmarks.coding_agents.shared.benchmark_backends import BenchmarkEndpoint
from scripts.benchmarks.coding_agents.shared.benchmark_requests import (
    BenchmarkRelay,
    observe_chunk,
    request_settings,
    summarize_requests,
)
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.tests.shared.http_server import request, server

SETTINGS = {"temperature": 0, "thinking": "low", "reasoning_budget": 2048, "seed": 42}
USAGE = {
    "prompt_tokens": 100,
    "completion_tokens": 20,
    "total_tokens": 120,
    "prompt_tokens_details": {"cached_tokens": 50},
    "completion_tokens_details": {"reasoning_tokens": 10},
}


class BenchmarkRequestsTests(unittest.TestCase):
    def test_cancelling_a_task_closes_its_inflight_backend_request(self):
        entered = threading.Event()
        disconnected = threading.Event()

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers["Content-Length"]))
                entered.set()
                self.connection.settimeout(3)
                if self.rfile.read(1) == b"":
                    disconnected.set()

        with server(Upstream) as url:
            endpoint = BenchmarkEndpoint("strata", "swift", url + "/v1", "test-key")
            with BenchmarkRelay(endpoint, SETTINGS) as relay:
                relay.task = "canceled"
                client = threading.Thread(
                    target=request,
                    args=(relay.client_endpoint().base_url + "/chat/completions", {"stream": True}),
                    daemon=True,
                )
                client.start()
                self.assertTrue(entered.wait(timeout=3))
                relay.cancel_task("canceled")
                client.join(timeout=3)
                self.assertFalse(client.is_alive())
                self.assertFalse(summarize_requests(relay.task_records("canceled"))["usage_complete"])
                self.assertTrue(disconnected.is_set())

    def test_every_backend_gets_common_limits_and_strata_mcp_is_disabled(self):
        for backend in ("strata", "llamacpp"):
            endpoint = BenchmarkEndpoint(backend, "swift", "http://127.0.0.1/v1", "secret", max_tokens=4096)
            body = {
                "model": "wrong",
                "temperature": 1,
                "max_completion_tokens": 8000,
                "stream": True,
                "strata_mcp": True,
                "reasoning": {"effort": "high"},
                "chat_template_kwargs": {"reasoning_effort": "high"},
            }
            result = request_settings(body, endpoint, SETTINGS)
            self.assertEqual((result["model"], result["temperature"], result["max_tokens"]), ("swift", 0, 4096))
            self.assertEqual(result["reasoning_effort"], "low")
            self.assertNotIn("max_completion_tokens", result)
            self.assertNotIn("strata_mcp", result)
            self.assertNotIn("reasoning", result)
            self.assertEqual(result["stream_options"], {"include_usage": True})
            result = request_settings({"max_tokens": 512}, endpoint, SETTINGS)
            self.assertEqual(result["max_tokens"], 512)
            result = request_settings(body, endpoint, {**SETTINGS, "thinking": "off"})
            self.assertFalse(result["chat_template_kwargs"]["enable_thinking"])

    def test_usage_events_are_not_counted_twice_and_reasoning_is_not_added_again(self):
        record = {"finished": True}
        observe_chunk(record, {"usage": USAGE}, 1)
        observe_chunk(record, {"usage": USAGE}, 2)
        metrics = summarize_requests([record, {"finished": True, "usage": USAGE}])
        self.assertEqual(metrics["total_tokens"], 240)
        self.assertEqual(metrics["prompt_tokens"], 200)
        self.assertEqual(metrics["completion_tokens"], 40)
        self.assertEqual(metrics["cached_tokens"], 100)
        self.assertEqual(metrics["reasoning_tokens"], 20)

    def test_missing_usage_and_interrupted_streams_are_not_zero_tokens(self):
        for records in (
            [],
            [{"finished": True}],
            [{"finished": False, "usage": USAGE}],
            [{"finished": True, "usage": USAGE}, {"finished": True, "status": 500}],
        ):
            with self.subTest(records=records):
                metrics = summarize_requests(records)
                self.assertFalse(metrics["usage_complete"])
                self.assertIsNone(metrics["total_tokens"])
        metrics = summarize_requests([{"finished": True, "usage": {**USAGE, "prompt_tokens_details": None}}])
        self.assertIsNone(metrics["cached_tokens"])

    def test_native_timings_roll_up_into_ttft_prefill_and_decode(self):
        records = [
            {
                "finished": True,
                "first_token_seconds": 31.0,
                "usage": {**USAGE, "prompt_tokens_details": {"cached_tokens": 0}},
                "native_timings": {
                    "prompt_n": 1000,
                    "prompt_ms": 10000,
                    "predicted_n": 40,
                    "predicted_ms": 2000,
                    "draft_n": 50,
                    "draft_n_accepted": 40,
                },
            },
            {
                "finished": True,
                "first_token_seconds": 3.0,
                "usage": {**USAGE, "prompt_tokens_details": {"cached_tokens": 900}},
                "native_timings": {
                    "prompt_n": 100,
                    "prompt_ms": 1000,
                    "predicted_n": 60,
                    "predicted_ms": 1000,
                    "draft_n": 30,
                    "draft_n_accepted": 15,
                },
            },
        ]
        metrics = summarize_requests(records)
        self.assertEqual(metrics["ttft_seconds"], 17.0)
        self.assertEqual(metrics["prefilled_tokens"], 1100)
        self.assertEqual(metrics["prefill_seconds"], 11.0)
        self.assertEqual(metrics["prefill_tokens_per_second"], 100.0)
        self.assertEqual(metrics["decode_tokens_per_second"], 33.3)
        self.assertEqual(metrics["draft_acceptance"], 0.688)

    def test_requests_without_native_timings_report_unavailable_not_zero(self):
        metrics = summarize_requests([{"finished": True, "usage": USAGE, "first_token_seconds": 2.0}])
        self.assertEqual(metrics["ttft_seconds"], 2.0)
        for key in ("prefilled_tokens", "prefill_seconds", "prefill_tokens_per_second", "decode_tokens_per_second"):
            self.assertIsNone(metrics[key])
        self.assertIsNone(metrics["draft_acceptance"])

    def test_streaming_relay_preserves_events_and_records_real_usage(self):
        received = []
        events = [
            {"choices": [{"delta": {"reasoning_content": "thinking"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "read"}}]}}]},
            {"choices": [], "usage": USAGE, "timings": {"predicted_n": 20, "predicted_per_second": 10}},
        ]
        wire = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n"

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                received.append(
                    (self.headers["Authorization"], json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(wire)

        with server(Upstream) as url:
            endpoint = BenchmarkEndpoint("strata", "swift", url + "/v1", "test-key")
            lifecycle = BenchmarkLifecycle(lambda: url + ":fixture-model")
            lifecycle.prepare(lambda: None, reused=True)
            lifecycle.warmup(lambda: None)
            with BenchmarkRelay(endpoint, SETTINGS, lifecycle=lifecycle) as relay:
                relay.task = "pi/proverb/1"
                status, content, _ = request(
                    relay.client_endpoint().base_url + "/chat/completions",
                    {"stream": True, "messages": [{"role": "user", "content": "solve"}]},
                )
                records = relay.task_records("pi/proverb/1")
        self.assertEqual((status, content), (200, wire))
        self.assertEqual(received[0][0], "Bearer test-key")
        self.assertEqual(summarize_requests(records)["total_tokens"], 120)
        self.assertIsNotNone(records[0]["first_token_seconds"])
        self.assertNotIn("test-key", json.dumps(records))
        self.assertEqual(records[0]["native_timings"]["predicted_n"], 20)
        timing = records[0]["benchmark"]["requests"][0]
        self.assertEqual(timing["status"], "completed")
        self.assertIn("first_output", timing["marks_seconds"])


if __name__ == "__main__":
    unittest.main()
