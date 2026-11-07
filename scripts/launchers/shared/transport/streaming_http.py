"""Owned chunked POST with incremental SSE reads; no model or turn policy."""

import http.client
import json
import queue
import threading
from urllib.parse import urlsplit
from typing import Any


class StreamingPost:
    def __init__(self, url: str, *, timeout: float = 15):
        address = urlsplit(url)
        if address.scheme != "http" or not address.hostname:
            raise ValueError("StreamingPost requires an HTTP URL")
        self.connection = http.client.HTTPConnection(address.hostname, address.port, timeout=timeout)
        self.target = address.path + ("?" + address.query if address.query else "")
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.done = threading.Event()
        self.finished = False
        self.reader: threading.Thread | None = None

    def start(self):
        self.connection.putrequest("POST", self.target)
        self.connection.putheader("Content-Type", "application/octet-stream")
        self.connection.putheader("Transfer-Encoding", "chunked")
        self.connection.endheaders()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            source = self.connection.sock
            assert source is not None
            # getresponse() may close the writer on Connection: close while upload is active.
            response = http.client.HTTPResponse(source, method="POST")
            response.begin()
            with response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}: {response.read(2000)!r}")
                if "text/event-stream" not in response.getheader("Content-Type", ""):
                    raise RuntimeError("Expected SSE response")
                while line := response.readline(1_048_577):
                    if len(line) > 1_048_576:
                        raise ValueError("SSE line exceeds 1 MiB")
                    self._line(line)
        except Exception as error:
            self.events.put({"type": "error", "error": str(error)})
        finally:
            self.done.set()

    def _line(self, line: bytes):
        if line.startswith(b"data:"):
            data = line[5:].strip()
            if data and data != b"[DONE]":
                self.events.put(json.loads(data))

    def send(self, data: bytes):
        if self.finished or self.done.is_set():
            raise RuntimeError("Cannot send to a finished stream")
        if data:
            self.connection.send(f"{len(data):x}\r\n".encode() + data + b"\r\n")

    def finish(self):
        if not self.finished:
            self.connection.send(b"0\r\n\r\n")
            self.finished = True

    def close(self):
        if self.connection.sock:
            import socket

            try:
                self.connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.connection.close()
        if self.reader:
            self.reader.join(timeout=1)
