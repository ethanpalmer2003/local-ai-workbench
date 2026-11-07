"""
- Generic JSON-rewriting HTTP proxy plumbing, shared by the service proxies
- The AUDIOCPP-specific TTS variant lives in tts_proxy.py
"""

import base64
import contextlib
import ipaddress
import json
import select
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager, ExitStack
from email.message import Message
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import urlsplit

from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import print_ready
from scripts.launchers.proxy_restart import ProxyRestartController

RequestScope = Callable[[str, str], AbstractContextManager[object]]

# ============================================================

_HOP_BY_HOP_REQUEST_HEADERS = ("host", "content-length", "connection")
_HOP_BY_HOP_RESPONSE_HEADERS = ("content-length", "transfer-encoding", "connection")


def build_forward_headers(client_headers: Message, body: bytes) -> dict[str, str]:
    headers = {k: v for k, v in client_headers.items() if k.lower() not in _HOP_BY_HOP_REQUEST_HEADERS}
    if body:
        headers.setdefault("Content-Type", "application/json")
    return headers


def relay_response_headers(
    handler: BaseHTTPRequestHandler, resp_headers: Iterable[tuple[str, str]], content_length: int
):
    """
    - Write upstream's response headers, minus hop-by-hop ones (we always
      buffer the body and send our own Content-Length)
    """
    handler.send_header("Access-Control-Allow-Origin", "*")
    for k, v in resp_headers:
        if k.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
            handler.send_header(k, v)
    handler.send_header("Content-Length", str(content_length))


def send_bytes(handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str | None = None):
    handler.send_response(status)
    handler.send_header("Access-Control-Allow-Origin", "*")
    if content_type:
        handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if body:
        handler.wfile.write(body)


def send_json_error(handler: BaseHTTPRequestHandler, status: int, message: str, error_type: str):
    body = json.dumps({"error": {"message": message, "type": error_type}}).encode("utf-8")
    send_bytes(handler, status, body, content_type="application/json")


def forward_upstream_error(handler: BaseHTTPRequestHandler, tag: str, error: urllib.error.URLError):
    if isinstance(error, urllib.error.HTTPError):
        with error:
            body = error.read()
        detail = body.decode("utf-8", errors="replace")
        with contextlib.suppress(json.JSONDecodeError):
            detail = json.dumps(json.loads(detail), indent=2)
        print(f"[{tag}] upstream HTTP {error.code}:\n{detail}")
        send_bytes(handler, error.code, body, error.headers.get("Content-Type", "application/json"))
    else:
        print(f"[{tag}] upstream unavailable: {error.reason}")
        send_json_error(handler, 502, f"upstream unavailable: {error.reason}", "bad_gateway")


def read_request_body(handler: BaseHTTPRequestHandler) -> bytes:
    raw_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_length)
    except ValueError as error:
        raise ValueError("Content-Length must be an integer") from error
    if length < 0:
        raise ValueError("Content-Length must not be negative")
    return handler.rfile.read(length) if length else b""


# ============================================================

RELAY_CHUNK_BYTES = 8192


class _SseAudioCounter:
    """
    - Counts decoded PCM bytes in SSE `speech.audio.delta` events
    - Stats only: a parse problem must never break the relay
    """

    def __init__(self) -> None:
        self.buffer = b""
        self.audio_bytes = 0

    def feed(self, chunk: bytes) -> None:
        self.buffer += chunk
        *lines, self.buffer = self.buffer.split(b"\n")
        for line in lines:
            if line.startswith(b"data: {") and b"speech.audio.delta" in line:
                self._count(line)

    def _count(self, line: bytes) -> None:
        with contextlib.suppress(Exception):
            event = json.loads(line[6:])
            encoded = event.get("audio") or event.get("delta") or ""
            self.audio_bytes += len(base64.b64decode(encoded))


def _send_stream_headers(
    handler: BaseHTTPRequestHandler,
    response: HTTPResponse,
    chunked: bool,
    length: str | None,
    response_headers: Mapping[str, str] | None = None,
) -> None:
    handler.send_response(response.status)
    handler.send_header("Access-Control-Allow-Origin", "*")
    overrides = {name.lower() for name in (response_headers or {})}
    for name, value in response.headers.items():
        if name.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS and name.lower() not in overrides:
            handler.send_header(name, value)
    for name, value in (response_headers or {}).items():
        handler.send_header(name, value)
    if chunked:
        handler.send_header("Transfer-Encoding", "chunked")
    else:
        handler.send_header("Content-Length", str(length))
    handler.end_headers()


def streamed_speech_response_headers(payload: Mapping[str, object]) -> dict[str, str] | None:
    """Describe AudioCpp's raw-PCM transport accurately to browser clients."""
    if payload.get("stream_format") == "audio" and payload.get("response_format") == "pcm":
        return {"Content-Type": "audio/pcm"}
    return None


def _write_chunk(handler: BaseHTTPRequestHandler, chunk: bytes, chunked: bool) -> None:
    handler.wfile.write(b"%X\r\n%s\r\n" % (len(chunk), chunk) if chunked else chunk)
    handler.wfile.flush()


def _watch_client_disconnect(client, response, stopped: threading.Event, disconnected: threading.Event) -> None:
    """Close an upstream response promptly when its downstream client aborts."""
    while not stopped.wait(0.05):
        try:
            readable, _, _ = select.select([client], [], [], 0)
        except (OSError, ValueError):
            readable = [client]
        if not readable:
            continue
        try:
            if client.recv(1, socket.MSG_PEEK):
                continue
        except (BlockingIOError, InterruptedError):
            continue
        except OSError:
            pass
        disconnected.set()
        http_response = getattr(response, "fp", None)
        buffered = getattr(http_response, "fp", None)
        raw = getattr(buffered, "raw", None)
        upstream_socket = getattr(raw, "_sock", None)
        if upstream_socket is not None:
            with contextlib.suppress(OSError):
                upstream_socket.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(Exception):
            response.close()
        return


def _pump_stream(
    handler: BaseHTTPRequestHandler,
    response: HTTPResponse,
    chunked: bool,
    counter: _SseAudioCounter | None,
    start: float,
    stats: dict[str, float],
) -> None:
    first_chunk = True
    while True:
        chunk = response.read1(RELAY_CHUNK_BYTES)
        if not chunk:
            break
        if first_chunk:
            stats["ttfb"] = time.perf_counter() - start
            first_chunk = False
        if counter:
            counter.feed(chunk)
        else:
            stats["audio_bytes"] += len(chunk)
        _write_chunk(handler, chunk, chunked)

    if chunked:
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()


def relay_stream(
    handler: BaseHTTPRequestHandler,
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    tag: str,
    response_headers: Mapping[str, str] | None = None,
) -> dict[str, float] | None:
    """
    - Forward one request and stream the response back as it arrives
    - The buffering run_json_proxy path cannot carry a token stream: every
      server-sent event has to reach the client before the response ends
    - Framing belongs to this side: upstream's Content-Length is reused when it
      has one, otherwise the body is re-chunked. The handler must therefore
      speak HTTP/1.1, or a chunked reply is not valid
    - Returns stats (ttfb, total, audio_bytes, disconnected), or None if
      upstream failed before streaming started
    """
    request = urllib.request.Request(url, data=body or None, method=method, headers=dict(headers))
    start = time.perf_counter()
    try:
        response = urllib.request.urlopen(request)
    except urllib.error.URLError as error:
        forward_upstream_error(handler, tag, error)
        return None

    stats: dict[str, float] = {"ttfb": 0.0, "total": 0.0, "audio_bytes": 0, "disconnected": 0}

    with response:
        length = response.headers.get("Content-Length")
        chunked = length is None
        is_sse = "text/event-stream" in response.headers.get("Content-Type", "")
        counter = _SseAudioCounter() if is_sse else None
        stopped = threading.Event()
        disconnected = threading.Event()
        watcher = threading.Thread(
            target=_watch_client_disconnect, args=(handler.connection, response, stopped, disconnected), daemon=True
        )
        watcher.start()

        try:
            _send_stream_headers(handler, response, chunked, length, response_headers)
            _pump_stream(handler, response, chunked, counter, start, stats)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            disconnected.set()
        except Exception:
            if not disconnected.is_set():
                raise
        finally:
            stopped.set()
            watcher.join(timeout=0.2)

        if disconnected.is_set():
            handler.close_connection = True
            stats["disconnected"] = 1
            print(f"[{tag}] client cancelled; upstream request closed")

        if counter:
            stats["audio_bytes"] = counter.audio_bytes

    stats["total"] = time.perf_counter() - start
    return stats


class ProxyHandlerMixin(BaseHTTPRequestHandler):
    """
    - Shared do_POST/do_GET/do_OPTIONS wiring; subclasses define `_forward`
    """

    def _forward(self, method: str) -> None:
        raise NotImplementedError

    restart_controller: ProxyRestartController | None = None
    request_scope: ClassVar[RequestScope | None] = None

    def _dispatch(self, method: str) -> None:
        with ExitStack() as stack:
            scope = type(self).request_scope
            if scope is not None:
                try:
                    stack.enter_context(scope(method, self.path))
                except Exception as error:
                    traceback.print_exc()
                    self.close_connection = True
                    send_json_error(self, 503, str(error), "model_transition_failed")
                    return
            self._forward(method)

    def do_POST(self):
        if not handle_restart(self, "POST", self.restart_controller):
            if self.restart_controller and self.restart_controller.state["status"] == "restarting":
                self.close_connection = True
                send_json_error(self, 503, "Service is restarting; retry after completion", "service_restarting")
                return
            self._dispatch("POST")

    def do_GET(self):
        if not handle_restart(self, "GET", self.restart_controller):
            self._dispatch("GET")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()


# ============================================================


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """
    - Refuses to share its port
    - Windows SO_REUSEADDR lets a second server bind a port that is already
      listening, which stacks two servers and sends every request to whichever
      bound first; every proxy here owns its port, so a taken port has to fail
      the bind loudly instead
    """

    allow_reuse_address = False

    def handle_error(self, request, client_address):
        """Ignore expected client disconnects instead of printing a traceback."""
        error_type = sys.exc_info()[0]
        if error_type and issubclass(error_type, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def serve_proxy(
    handler: type[BaseHTTPRequestHandler],
    listen_ip: str,
    listen_port: int,
    upstream_url: str,
    tag: str,
    on_server: Callable[[ThreadingHTTPServer], None] | None = None,
):
    controller = getattr(handler, "restart_controller", None)
    while True:
        with ExclusiveThreadingHTTPServer((listen_ip, listen_port), handler) as server:
            if on_server:
                on_server(server)
            if controller:
                controller.restart_listener = server.shutdown
            print(f"[{tag}] forwarding to {upstream_url}")
            print_ready(tag, port=listen_port)
            server.serve_forever()
        if not controller or not controller.listener_requested:
            return
        controller.listener_requested = False


class _JsonProxyHandler(ProxyHandlerMixin):
    """Relay JSON bodies, optionally transforming the request and observing the response."""

    # - set by run_json_proxy on the per-run subclass
    upstream_url: ClassVar[str] = ""
    transform: ClassVar[Any] = None
    tag: ClassVar[str] = "proxy"
    on_response: ClassVar[Any] = None
    transform_paths: ClassVar[frozenset[str] | None] = None
    request_scope: ClassVar[Any] = None
    restart_controller: ClassVar[Any] = None

    def _forward(self, method: str) -> None:
        prepared = self._prepare(method)
        if prepared is None:
            return
        body, raw_request = prepared
        self._relay(method, body, raw_request)

    def _applies(self) -> bool:
        return self.transform_paths is None or urlsplit(self.path).path in self.transform_paths

    def _prepare(self, method: str) -> tuple[bytes, dict[str, object] | None] | None:
        """Read and optionally transform the request; None means a response was already sent."""
        body = read_request_body(self)
        if not (self._applies() and body and (self.transform or self.on_response) and "json" in self._content_type()):
            return body, None
        try:
            raw_request = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            send_json_error(self, 400, "invalid JSON", "invalid_request")
            return None
        if not isinstance(raw_request, dict):
            return body, None
        if not self.transform:
            return body, raw_request
        try:
            # - transform gets a copy: it may mutate in place, while
            #   on_response needs the request as the client sent it
            payload = self.transform(dict(raw_request))
            encoded = None if payload is None else json.dumps(payload).encode("utf-8")
        except Exception:
            traceback.print_exc()
            send_json_error(self, 500, "proxy error", "proxy_error")
            return None
        if encoded is None:
            send_bytes(self, 204, b"")
            return None
        return encoded, raw_request

    def _content_type(self) -> str:
        return self.headers.get("Content-Type", "").lower()

    def _relay(self, method: str, body: bytes, raw_request: dict[str, object] | None) -> None:
        req = urllib.request.Request(
            self.upstream_url + self.path,
            data=body if body else None,
            method=method,
            headers=build_forward_headers(self.headers, body),
        )
        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                if self.on_response and raw_request is not None:
                    self._notify_response(resp_body, raw_request)
                self.send_response(resp.status)
                relay_response_headers(self, resp.getheaders(), len(resp_body))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.URLError as e:
            forward_upstream_error(self, self.tag, e)
            if self.request_scope is not None and method == "POST":
                raise

    def _notify_response(self, body: bytes, raw_request: dict[str, object]) -> None:
        try:
            response_payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(response_payload, dict) or self.on_response is None:
            return
        try:
            self.on_response(response_payload, raw_request)
        except Exception:
            traceback.print_exc()

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.tag}] {format % args}")


def run_json_proxy(
    service: cfg.GenericStartupServiceSettings,
    upstream_url: str,
    transform: Callable[[dict[str, object]], dict[str, object] | None] | None = None,
    tag: str = "proxy",
    on_response: Callable[[dict[str, object], dict[str, object]], None] | None = None,
    restart_controller: ProxyRestartController | None = None,
    transform_paths: frozenset[str] | None = None,
    request_scope: RequestScope | None = None,
    on_server: Callable[[ThreadingHTTPServer], None] | None = None,
):
    """
    - Blocks forever
    - transform(payload) -> payload or None (None skips upstream and responds 204)
    - Non-JSON bodies pass through untouched
    - on_response(response_payload, raw_request_payload) fires after each
      successful JSON upstream response, with the request as the CLIENT sent
      it (pre-transform)
    - Hook errors are logged, never break the relay
    """
    attributes: dict[str, object] = {
        "upstream_url": upstream_url,
        "tag": tag,
        "on_response": on_response,
        "transform_paths": transform_paths,
        "request_scope": request_scope,
        "restart_controller": restart_controller,
    }
    # - plain function attributes would bind as methods and receive self
    if transform is not None:
        attributes["transform"] = staticmethod(transform)
    if on_response is not None:
        attributes["on_response"] = staticmethod(on_response)
    handler = type("ProxyHandler", (_JsonProxyHandler,), attributes)
    print(f"[{tag}] service: {service}")
    serve_proxy(handler, service.listen_ip, service.port, upstream_url, tag, on_server)


def handle_restart(handler: BaseHTTPRequestHandler, method: str, controller: ProxyRestartController | None) -> bool:
    if urlsplit(handler.path).path != "/proxy/restart":
        return False

    def local_host(value: str) -> bool:
        return value in ("localhost", "127.0.0.1", "::1")

    origin = handler.headers.get("Origin")
    host = urlsplit("//" + handler.headers.get("Host", "")).hostname or ""
    if (
        not ipaddress.ip_address(handler.client_address[0]).is_loopback
        or not local_host(host)
        or (origin and not local_host(urlsplit(origin).hostname or ""))
    ):
        handler.close_connection = True
        send_json_error(handler, 403, "Restart management is local-only", "forbidden")
        return True
    if controller is None:
        handler.close_connection = True
        send_json_error(handler, 501, "This launcher does not support restart management", "unsupported")
        return True
    try:
        if method == "POST":
            if (
                handler.headers.get_content_type() != "application/json"
                or not 0 < int(handler.headers.get("Content-Length", "0")) <= 1024
            ):
                raise ValueError("Expected a small JSON object with a restart target")
            payload = json.loads(read_request_body(handler))
            if (
                not isinstance(payload, dict)
                or set(payload) != {"target"}
                or payload["target"] not in ("backend", "proxy", "both")
            ):
                raise ValueError("Expected target: backend, proxy or both")
            controller.start(payload["target"])
        send_bytes(
            handler, 202 if method == "POST" else 200, json.dumps(controller.snapshot()).encode(), "application/json"
        )
    except BlockingIOError as error:
        send_json_error(handler, 409, str(error), "restart_in_progress")
    except (ValueError, UnicodeDecodeError) as error:
        handler.close_connection = True
        send_json_error(handler, 400, str(error), "invalid_restart")
    return True
