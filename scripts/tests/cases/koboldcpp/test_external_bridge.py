"""Lite's generation paths are answered by the external llama.cpp server, not the no-model Kobold."""

import io
import json
import unittest
from http.server import BaseHTTPRequestHandler

from scripts.launchers.koboldcpp import external_bridge
from scripts.shared.http_server import request, server

CHAT_PATH = "/v1/chat/completions"


class _Llama(BaseHTTPRequestHandler):
    """A chat-only upstream: a completion request here is the bug this bridge exists to avoid."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == CHAT_PATH, self.path
        assert isinstance(body.get("messages"), list), body
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for token in ("Hello", " there"):
                choice = {"delta": {"content": token}}
                self.wfile.write(b"data: " + json.dumps({"choices": [choice]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = json.dumps({"choices": [{"message": {"content": "Hello there"}}]}).encode()
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
    def test_kobold_payload_becomes_a_chat_request_that_keeps_the_template(self):
        request_body = external_bridge.chat_request(
            {
                "prompt": "Once upon",
                "memory": "You are a helpful assistant.",
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
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Once upon"},
                ],
                "max_tokens": 64,
                "stream": True,
                "temperature": 0.7,
                "repetition_penalty": 1.1,
                "stop": ["\nUser:", "\n###"],
            },
        )

    def test_a_prompt_without_memory_is_one_user_turn(self):
        request_body = external_bridge.chat_request({"prompt": "hi", "max_length": 8}, stream=False)
        self.assertEqual(request_body["messages"], [{"role": "user", "content": "hi"}])

    def test_streamed_token_reads_chat_deltas_and_completion_text(self):
        delta = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n'
        self.assertEqual(external_bridge.streamed_token(delta), "hi")
        plain = b'data: {"choices":[{"text":"hi"}]}\n'
        self.assertEqual(external_bridge.streamed_token(plain), "hi")
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
            status, body, _ = request(base + CHAT_PATH, {"messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(status, 200)
            self.assertEqual(external_bridge.completion_text(body), "Hello there")


if __name__ == "__main__":
    unittest.main()
