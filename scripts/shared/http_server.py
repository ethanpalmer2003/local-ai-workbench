"""HTTP and media fixtures shared by mocked and live workflow checks."""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def request(
    url: str, payload: dict[str, object] | bytes | None = None, method: str | None = None, timeout: float = 5
) -> tuple[int, bytes, str]:
    body = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer smoke-test"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(), error.headers.get("Content-Type", "")


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
