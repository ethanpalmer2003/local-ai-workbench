"""Lite's generation paths are answered by the external llama.cpp server, not the no-model Kobold."""

import io
import json
import unittest
from http.server import BaseHTTPRequestHandler

from scripts.launchers.koboldcpp import external_bridge
from scripts.tests.shared.http_server import request, server


class _Llama(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/v1/completions", self.path
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for token in ("Hello", " there"):
                self.wfile.write(b"data: " + json.dumps({"choices": [{"text": token}]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = json.dumps({"choices": [{"text": "Hello there"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class _Handler:
    """Just enough of a request handler to capture what serve-side code writes."""

    def __init__(self) -> None:
        self.wfile = io.BytesIO()
        self.status = 0
        self.headers: list[tuple[str, str]] = []
        self.close_connection = False

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def end_headers(self) -> None:
        return


class ExternalBridgeTests(unittest.TestCase):
    def test_kobold_payload_becomes_an_openai_completion_request(self):
        request_body = external_bridge.openai_request(
            {
                "prompt": "Once upon",
                "max_length": 64,
                "temperature": 0.7,
                "rep_pen": 1.1,
                "stop_sequence": ["\nUser:", {"sequence": "\n###"}],
                "sampler_order": [6, 0, 1],
            },
            stream=True,
        )
        self.assertEqual(
            request_body,
            {
                "prompt": "Once upon",
                "max_tokens": 64,
                "stream": True,
                "temperature": 0.7,
                "repetition_penalty": 1.1,
                "stop": ["\nUser:", "\n###"],
            },
        )

    def test_streamed_token_reads_only_real_deltas(self):
        line = b'data: {"choices":[{"text":"hi"}]}\n'
        self.assertEqual(external_bridge.streamed_token(line), "hi")
        self.assertEqual(external_bridge.streamed_token(b"data: [DONE]\n"), "")
        self.assertEqual(external_bridge.streamed_token(b"\n"), "")

    def test_generation_is_forwarded_to_the_external_endpoint(self):
        with server(_Llama) as base:
            body = json.dumps({"prompt": "hi", "max_length": 16}).encode()
            handler = _Handler()
            external_bridge.respond(handler, base + "/v1", "/api/v1/generate", body)
            self.assertEqual(handler.status, 200)
            self.assertEqual(json.loads(handler.wfile.getvalue()), {"results": [{"text": "Hello there"}]})

            streamed = _Handler()
            external_bridge.respond(streamed, base + "/v1", external_bridge.STREAM_PATH, body)
            frames = streamed.wfile.getvalue().decode()
            parsed = [json.loads(line[len("data: ") :]) for line in frames.splitlines() if line.startswith("data: ")]
            self.assertEqual([item["token"] for item in parsed], ["Hello", " there"])
            self.assertEqual(streamed.headers[0], ("Content-Type", "text/event-stream"))

    def test_the_proxy_answers_generation_paths_when_an_external_endpoint_is_set(self):
        with server(_Llama) as base:
            self.assertIn("/api/extra/generate/stream", external_bridge.GENERATE_PATHS)
            self.assertIn("/api/v1/generate", external_bridge.GENERATE_PATHS)
            status, body, _ = request(base + "/v1/completions", {"prompt": "hi", "max_tokens": 8})
            self.assertEqual(status, 200)
            self.assertEqual(external_bridge.completion_text(body), "Hello there")


if __name__ == "__main__":
    unittest.main()
