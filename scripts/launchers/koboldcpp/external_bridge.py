"""Serve Lite's Kobold-protocol generation from the external llama.cpp server.

The embedded Lite keeps posting to its own origin even when an OpenAI provider is configured, so the
proxy answers those two paths itself instead of forwarding a payload the no-model Kobold cannot serve.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from typing import Any

from scripts.launchers.proxy_util import send_bytes

STREAM_PATH = "/api/extra/generate/stream"
GENERATE_PATHS = (STREAM_PATH, "/api/v1/generate")

# - Kobold field -> OpenAI completion field; unknown keys stay out of the upstream request
PASSTHROUGH = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "rep_pen": "repetition_penalty",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
}


def openai_request(payload: dict[str, Any], stream: bool) -> dict[str, Any]:
    request: dict[str, Any] = {
        "prompt": str(payload.get("prompt") or ""),
        "max_tokens": int(payload.get("max_length") or 128),
        "stream": stream,
    }
    for source, target in PASSTHROUGH.items():
        value = payload.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            request[target] = value
    stops = [
        str(item.get("sequence", "") if isinstance(item, dict) else item)
        for item in payload.get("stop_sequence") or []
    ]
    if stops := [stop for stop in stops if stop]:
        request["stop"] = stops
    return request


def frame(token: str) -> bytes:
    """One Lite SSE message frame."""
    return f"event: message\ndata: {json.dumps({'token': token})}\n\n".encode()


def streamed_token(line: bytes) -> str:
    """Text carried by one llama.cpp server-sent event, or an empty string."""
    line = line.strip()
    if not line.startswith(b"data:"):
        return ""
    data = line[5:].strip()
    if not data or data == b"[DONE]":
        return ""
    try:
        choices = json.loads(data).get("choices") or []
    except json.JSONDecodeError:
        return ""
    return str(choices[0].get("text") or "") if choices else ""


def completion_text(body: bytes) -> str:
    choices = json.loads(body or b"{}").get("choices") or []
    return str(choices[0].get("text") or "") if choices else ""


def _call(base: str, request: dict[str, Any]) -> Any:
    url = base.rstrip("/") + "/completions"
    payload = json.dumps(request).encode("utf-8")
    return urllib.request.urlopen(
        urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}), timeout=300
    )


def generated_text(base: str, payload: dict[str, Any]) -> str:
    with _call(base, openai_request(payload, stream=False)) as response:
        return completion_text(response.read())


def tokens(base: str, payload: dict[str, Any]) -> Iterator[str]:
    with _call(base, openai_request(payload, stream=True)) as response:
        for line in response:
            if token := streamed_token(line):
                yield token


def respond(handler: Any, base: str, path: str, body: bytes) -> None:
    """Answer one Lite generation request from the external server, in the shapes Lite parses."""
    payload = json.loads(body or b"{}")
    if path != STREAM_PATH:
        text = generated_text(base, payload)
        send_bytes(handler, 200, json.dumps({"results": [{"text": text}]}).encode(), "application/json")
        return
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True
    try:
        for token in tokens(base, payload):
            handler.wfile.write(frame(token))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        return
