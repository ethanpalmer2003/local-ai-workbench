"""HTTP and media fixtures shared by mocked and live workflow checks."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import requests


def request(
    url: str, payload: dict[str, object] | bytes | None = None, method: str | None = None, timeout: float = 5
) -> tuple[int, bytes, str]:
    structured = payload if isinstance(payload, dict) else None
    raw = payload if not isinstance(payload, dict) else None
    response = requests.request(
        method or ("POST" if payload is not None else "GET"),
        url,
        json=cast(Any, structured),
        data=raw,
        headers={"Content-Type": "application/json", "Authorization": "Bearer smoke-test"},
        timeout=timeout,
    )
    return response.status_code, response.content, response.headers.get("Content-Type", "")


@contextlib.contextmanager
def server(handler: type[BaseHTTPRequestHandler]) -> Generator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("fixture HTTP server did not stop")
