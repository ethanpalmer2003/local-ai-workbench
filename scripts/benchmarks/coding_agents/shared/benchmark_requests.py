"""OpenAI-compatible relay: common request limits and server-reported usage for every harness."""

import json
import socket
import statistics
import threading
import time
import urllib.request
from contextlib import closing, suppress
from dataclasses import replace
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import urlsplit

from scripts.benchmarks.coding_agents.shared.benchmark_backends import BenchmarkEndpoint
from scripts.benchmarks.shared.benchmark import BenchmarkContractError, BenchmarkLifecycle


def request_settings(body: dict[str, Any], endpoint: BenchmarkEndpoint, settings: dict[str, Any]) -> dict[str, Any]:
    requested = body.get("max_tokens", body.get("max_completion_tokens"))
    cap = min(requested, endpoint.max_tokens) if isinstance(requested, int) and requested > 0 else endpoint.max_tokens
    body = {
        **body,
        "model": endpoint.model,
        "temperature": settings["temperature"],
        "max_tokens": cap,
        "seed": settings.get("seed", 42),
    }
    for key in ("reasoning", "thinking", "enable_thinking"):
        body.pop(key, None)
    body.pop("max_completion_tokens", None)
    body.pop("strata_mcp", None)
    kwargs = dict(body.get("chat_template_kwargs") or {})
    for key in ("reasoning_effort", "enable_thinking"):
        kwargs.pop(key, None)
    effort = settings["thinking"]
    if effort == "off":
        body.pop("reasoning_effort", None)
        kwargs["enable_thinking"] = False
        body["thinking_budget_tokens"] = 0
        if endpoint.backend == "strata":
            body["reasoning_effort"] = "none"
            body["reasoning_budget_tokens"] = 0
    else:
        if effort != "default":
            body["reasoning_effort"] = effort
        else:
            body.pop("reasoning_effort", None)
        body["thinking_budget_tokens"] = settings["reasoning_budget"]
        if endpoint.backend == "strata":
            body["reasoning_budget_tokens"] = settings["reasoning_budget"]
    body["chat_template_kwargs"] = kwargs
    if body.get("stream"):
        body["stream_options"] = {**(body.get("stream_options") or {}), "include_usage": True}
    return body


def observe_chunk(record: dict[str, Any], chunk: dict[str, Any], elapsed: float) -> None:
    if isinstance(chunk.get("usage"), dict) and chunk["usage"]:
        record["usage"] = chunk["usage"]
    if chunk.get("timings"):
        record["native_timings"] = chunk["timings"]
    choices = chunk.get("choices") or []
    generated = any(
        any(choice.get("delta", {}).get(key) for key in ("content", "reasoning_content", "reasoning", "tool_calls"))
        for choice in choices
    )
    if generated and record.get("first_token_seconds") is None:
        record["first_token_seconds"] = elapsed


def stream_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Native latency and throughput, independent of token accounting.

    Prefill and decode come from each server's own `timings` block, so both arms
    share one scope. `prefilled_tokens` counts only tokens the server actually
    prefilled (`prompt_n`), which is smaller than `prompt_tokens` whenever a
    prefix cache was reused. A request without `native_timings` contributes
    nothing rather than a zero.
    """
    prefilled = predicted = draft = accepted = 0.0
    prefill_ms = predicted_ms = 0.0
    first_tokens: list[float] = []
    native = False
    for record in records:
        if not record.get("finished"):
            continue
        latency = record.get("first_token_seconds")
        if isinstance(latency, (int, float)):
            first_tokens.append(float(latency))
        timing = record.get("native_timings")
        if not isinstance(timing, dict):
            continue
        native = True
        prefilled += timing.get("prompt_n") or 0
        prefill_ms += timing.get("prompt_ms") or 0
        predicted += timing.get("predicted_n") or 0
        predicted_ms += timing.get("predicted_ms") or 0
        draft += timing.get("draft_n") or 0
        accepted += timing.get("draft_n_accepted") or 0
    return {
        "ttft_seconds": round(statistics.median(first_tokens), 3) if first_tokens else None,
        "prefilled_tokens": int(prefilled) if native else None,
        "prefill_seconds": round(prefill_ms / 1000, 3) if native and prefill_ms else None,
        "prefill_tokens_per_second": round(prefilled / (prefill_ms / 1000), 1) if native and prefill_ms else None,
        "decode_tokens_per_second": round(predicted / (predicted_ms / 1000), 1) if native and predicted_ms else None,
        "draft_acceptance": round(accepted / draft, 3) if draft else None,
    }


def stream_chat(
    connection: Any, body: dict[str, Any], *, timeout: float, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One streaming chat completion, recorded the same way for every Strata benchmark."""
    query = urllib.request.Request(
        connection.base_url + "/chat/completions",
        json.dumps(body).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer " + connection.api_key},
    )
    started = time.perf_counter()
    record: dict[str, Any] = {"content": "", "finished": False, **(extra or {})}
    with urllib.request.urlopen(query, timeout=timeout) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                record["finished"] = True
                break
            chunk = json.loads(payload)
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            observe_chunk(record, chunk, time.perf_counter() - started)
            for choice in chunk.get("choices", []):
                record["content"] += choice.get("delta", {}).get("content") or ""
                if choice.get("finish_reason"):
                    record["finish_reason"] = choice["finish_reason"]
    record["seconds"] = time.perf_counter() - started
    record["accounting"] = summarize_requests([record])
    return record


def summarize_requests(records: list[dict[str, Any]]) -> dict[str, Any]:
    complete = bool(records) and all(
        record.get("finished")
        and isinstance(record.get("usage"), dict)
        and all(
            isinstance(record["usage"].get(key), int) for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        for record in records
    )
    result: dict[str, Any] = {
        "api_requests": len(records),
        "usage_complete": complete,
        "requests_with_usage": sum(bool(record.get("usage")) for record in records),
    }
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        result[key] = sum(record["usage"][key] for record in records) if complete else None
    for label, group, key in (
        ("cached_tokens", "prompt_tokens_details", "cached_tokens"),
        ("reasoning_tokens", "completion_tokens_details", "reasoning_tokens"),
    ):
        values = [((record.get("usage") or {}).get(group) or {}).get(key) for record in records]
        numeric = [value for value in values if isinstance(value, int)]
        result[label] = sum(numeric) if complete and numeric and len(numeric) == len(values) else None
    measured = [request for record in records for request in record.get("benchmark", {}).get("requests", [])]
    result["api_timing_scope"] = (
        "resident_request"
        if records and all("benchmark" in record for record in records)
        else "unclassified_fixture_or_legacy"
    )
    result["api_seconds"] = (
        round(sum(request["request_seconds"] for request in measured if request["status"] == "completed"), 3)
        if result["api_timing_scope"] == "resident_request"
        else round(sum(record.get("seconds", 0) for record in records), 3)
    )
    result.update(stream_metrics(records))
    return result


def warmup(endpoint: BenchmarkEndpoint, tokens: int = 64) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": endpoint.model,
        "messages": [
            {
                "role": "user",
                "content": "Write a Python function that returns the sum of the squares in a list. Output code only.",
            }
        ],
        "max_tokens": tokens,
        "temperature": 0,
        "seed": 42,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "thinking_budget_tokens": 0,
    }
    if endpoint.backend == "strata":
        body["reasoning_effort"] = "none"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {endpoint.api_key}"}
    request = urllib.request.Request(endpoint.base_url + "/chat/completions", json.dumps(body).encode(), headers)
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.load(response)
    return {"seconds": time.perf_counter() - started, "usage": result.get("usage"), "max_tokens": tokens}


class BenchmarkRelay:
    def __init__(
        self, endpoint: BenchmarkEndpoint, settings: dict[str, Any], *, lifecycle: BenchmarkLifecycle | None = None
    ) -> None:
        self.endpoint = endpoint
        self.settings = settings
        self.lifecycle = lifecycle
        self.records: list[dict[str, Any]] = []
        self.task = "warmup"
        self.lock = threading.Lock()
        self.active: dict[int, tuple[str, socket.socket]] = {}
        self.canceled: set[str] = set()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "BenchmarkRelay":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.cancel_task()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)

    def client_endpoint(self) -> BenchmarkEndpoint:
        if self.server is None:
            raise RuntimeError("Start the relay before preparing a client")
        return replace(self.endpoint, base_url=f"http://127.0.0.1:{self.server.server_port}/v1", api_key="noop")

    def task_records(self, task: str) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(record) for record in self.records if record["task"] == task]

    def cancel_task(self, task: str | None = None) -> None:
        with self.lock:
            if task:
                self.canceled.add(task)
            sockets = [connection for label, connection in self.active.values() if task is None or task == label]
        for connection in sockets:
            with suppress(OSError):  # The response may have closed after the snapshot.
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.lock:
                if not any(task is None or label == task for label, _ in self.active.values()):
                    return
            time.sleep(0.01)
        raise TimeoutError("A benchmark API request did not stop after cancellation")

    def handler(self) -> type[BaseHTTPRequestHandler]:
        return type("Handler", (_BenchmarkRelayHandler,), {"relay": self})


class _RelayRequest:
    """Per-request bookkeeping shared by the relay handler stages."""

    def __init__(self, record: dict[str, Any], started: float) -> None:
        self.record = record
        self.started = started
        self.timer: Any = None
        self.scope: Any = None
        self.timing: Any = None
        self.response_started = False

    def begin_timing(self, lifecycle: BenchmarkLifecycle | None) -> None:
        if lifecycle is None:
            return
        self.timer = lifecycle.fork()
        self.scope = self.timer.request()
        self.timing = self.scope.__enter__()

    def finish_timing(self) -> None:
        if self.timer is None or self.scope is None or self.timing is None:
            return
        if not self.record["finished"] or self.record.get("error"):
            self.timing.reject(str(self.record.get("error", "Incomplete or failed backend response")))
        try:
            self.scope.__exit__(None, None, None)
        except BenchmarkContractError as error:
            self.record["error"] = str(error)
        self.record["benchmark"] = self.timer.record()


_REQUEST_SETTING_KEYS = (
    "model",
    "temperature",
    "max_tokens",
    "seed",
    "reasoning_effort",
    "thinking_budget_tokens",
    "reasoning_budget_tokens",
    "chat_template_kwargs",
)


class _BenchmarkRelayHandler(BaseHTTPRequestHandler):
    """One run's relay: forwards chat completions and records what the server reports."""

    relay: ClassVar[Any]

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        relay = type(self).relay
        if self.path.rstrip("/") not in ("/v1/models", "/models"):
            self.send_error(404)
            return
        body = json.dumps({"data": [{"id": relay.endpoint.model, "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        relay = type(self).relay
        if self.path != "/v1/chat/completions":
            self.send_error(404, "This benchmark uses OpenAI chat completions")
            return
        record: dict[str, Any] = {"task": relay.task, "finished": False, "first_token_seconds": None}
        request = _RelayRequest(record, time.perf_counter())
        with relay.lock:
            relay.records.append(record)
        try:
            request.begin_timing(relay.lifecycle)
            self._forward(request, self._prepared_body(record))
        except (OSError, HTTPException, BenchmarkContractError) as error:
            record["error"] = str(error)
            if not request.response_started:
                with suppress(OSError):  # The client may already have closed the connection.
                    self.send_error(502, "Backend request failed")
        finally:
            record["seconds"] = round(time.perf_counter() - request.started, 6)
            request.finish_timing()
            with relay.lock:
                relay.active.pop(id(record), None)

    def _prepared_body(self, record: dict[str, Any]) -> dict[str, Any]:
        relay = type(self).relay
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body = request_settings(body, relay.endpoint, relay.settings)
        record["request_settings"] = {key: body[key] for key in _REQUEST_SETTING_KEYS if key in body}
        return body

    def _forward(self, request: _RelayRequest, body: dict[str, Any]) -> None:
        relay = type(self).relay
        record = request.record
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {relay.endpoint.api_key}"}
        url = urlsplit(relay.endpoint.base_url)
        with closing(HTTPConnection(url.hostname or "127.0.0.1", url.port, timeout=600)) as connection:
            connection.request("POST", url.path.rstrip("/") + "/chat/completions", json.dumps(body).encode(), headers)
            if connection.sock is None:
                raise ConnectionError("Backend socket is unavailable")
            with relay.lock:
                relay.active[id(record)] = (record["task"], connection.sock)
                canceled = record["task"] in relay.canceled
            if canceled:
                raise ConnectionAbortedError("Task was canceled")
            response = connection.getresponse()
            record["status"] = response.status
            self.send_response(response.status)
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
            self.end_headers()
            request.response_started = True
            if response.status >= 400:
                self.wfile.write(response.read())
                return
            self._write_payload(response, request, bool(body.get("stream")))
        record["finished"] = not body.get("stream") or bool(record.get("stream_done"))

    def _write_payload(self, response: Any, request: _RelayRequest, streaming: bool) -> None:
        if not streaming:
            content = response.read()
            observe_chunk(request.record, json.loads(content), time.perf_counter() - request.started)
            self.wfile.write(content)
            return
        self._stream_response(response, request.record, request.started, request.timing)

    def _stream_response(self, response: Any, record: dict[str, Any], started: float, timing: Any = None) -> None:
        for line in response:
            if line.startswith(b"data:"):
                data = line[5:].strip()
                if data and data != b"[DONE]":
                    observe_chunk(record, json.loads(data), time.perf_counter() - started)
                    if timing is not None and record.get("first_token_seconds") is not None:
                        timing.mark("first_output")
                elif data == b"[DONE]":
                    record["stream_done"] = True
            self.wfile.write(line)
            self.wfile.flush()
