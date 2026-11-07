"""Lazy llama.cpp proxy: owns the client port and starts llama-server on demand.

- Answers /health and /v1/models from configuration, so a harness can point at
  it and sync its route without paying for a model load
- The first request that needs the model starts llama-server on the internal
  port, waits for readiness, then streams the reply through untouched
- Stops llama-server again after `idle-timeout-s` with nothing in flight, which
  is what gives the VRAM back
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import threading
import time
from typing import Any, ClassVar

from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import backend_running, kill_process_tree, kill_processes_on_ports, launch_module
from scripts.launchers.llamacpp import llamacpp
from scripts.launchers.proxy_util import (
    ProxyHandlerMixin,
    build_forward_headers,
    read_request_body,
    relay_stream,
    send_bytes,
    serve_proxy,
)

TAG = "llamacpp-proxy"
IDLE_POLL_SECONDS = 30

# - what another launcher names to run this proxy as its own process
MODULE = "scripts.launchers.llamacpp.llamacpp_proxy"
TITLE = "LlamaCpp Proxy"


def running() -> bool:
    """True when a proxy already answers the client port"""
    return backend_running(int(cfg.LLAMACPP_SERVICE.port))


def start(args: argparse.Namespace, port: int | None = None) -> None:
    """Run this proxy with another launcher's server-config flags"""
    extra_args = llamacpp.config_argv(args)
    if port is not None:
        extra_args.extend(["--port", str(port)])
    _ = launch_module(MODULE, TITLE, extra_args=extra_args)


class Backend:
    """llama-server's lifecycle behind the proxy's client port"""

    def __init__(self, conf: llamacpp.LlamaConfig, idle_timeout_s: int) -> None:
        self.conf = conf
        self.port = conf.port
        self.idle_timeout_s = idle_timeout_s
        self._lock = threading.Lock()
        self._in_flight = 0
        self._last_used = time.monotonic()
        self._proc: subprocess.Popen[Any] | None = None

    @property
    def loaded(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def acquire(self) -> None:
        """Block until llama-server is ready, counting one request in flight"""
        with self._lock:
            if not self.loaded:
                self._start()
            self._in_flight += 1
            self._last_used = time.monotonic()

    def release(self) -> None:
        with self._lock:
            self._in_flight -= 1
            self._last_used = time.monotonic()

    def _start(self) -> None:
        """Caller holds the lock; MERGE keeps the server windowless and lets the
        job object take it down with this proxy"""
        print(f"[{TAG}] loading profile '{self.conf.name}' on port {self.port}")
        self._proc = llamacpp.launch(conf=self.conf, mode=cfg.ConsoleTerminalLaunchMode.MERGE)

    def _stop(self) -> None:
        """Caller holds the lock"""
        proc = self._proc
        if proc is None:
            return

        if proc.poll() is None:
            # - taskkill clears the tree, but the harness terminal's sandbox
            #   denies it; the direct handle is the fallback that still works
            kill_process_tree(proc.pid)

        if proc.poll() is None:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                _ = proc.wait(timeout=10)

        kill_processes_on_ports(self.port)

        if proc.poll() is None:
            # - keep an unkillable server registered: dropping it would leak its
            #   VRAM and let the next request stack a second one on the port
            print(f"[{TAG}] WARN: llama-server {proc.pid} survived the unload; keeping it loaded")
            return

        self._proc = None
        print(f"[{TAG}] llama-server stopped")

    def stop_if_idle(self) -> None:
        with self._lock:
            if not self.loaded or self._in_flight > 0:
                return

            idle_for = time.monotonic() - self._last_used
            if idle_for < self.idle_timeout_s:
                return

            print(f"[{TAG}] idle {int(idle_for)}s - unloading")
            self._stop()


class Handler(ProxyHandlerMixin):
    # - re-chunked replies need HTTP/1.1; the buffering proxies stay on 1.0
    protocol_version = "HTTP/1.1"

    backend: ClassVar[Backend]

    def _forward(self, method: str) -> None:
        path = self.path.split("?", 1)[0]

        if method == "GET" and path == "/health":
            self._send_health()
            return

        if method == "GET" and path == "/v1/models":
            self._send_models()
            return

        body = read_request_body(self)
        self.backend.acquire()
        try:
            relay_stream(
                self,
                method,
                f"http://127.0.0.1:{self.backend.port}{self.path}",
                build_forward_headers(self.headers, body),
                body,
                TAG,
            )
        except (BrokenPipeError, ConnectionResetError):
            # - the caller hung up mid-stream (a cancelled request); there is
            #   nothing to report and this connection cannot be reused
            self.close_connection = True
        finally:
            self.backend.release()

    def _send_health(self) -> None:
        payload = {
            "status": "ok",
            "backend": "loaded" if self.backend.loaded else "unloaded",
            "profile": self.backend.conf.name,
            "idle_timeout_s": self.backend.idle_timeout_s,
        }
        send_bytes(self, 200, json.dumps(payload).encode("utf-8"), content_type="application/json")

    def _send_models(self) -> None:
        # - from the profile, so discovery costs no model load
        entry = {"id": self.backend.conf.alias, "object": "model", "owned_by": "llamacpp"}
        body = json.dumps({"object": "list", "data": [entry]}).encode("utf-8")
        send_bytes(self, 200, body, content_type="application/json")

    def log_message(self, format, *args):
        print(f"[{TAG}] {format % args}")


def _watch_idle(backend: Backend) -> None:
    while True:
        time.sleep(min(IDLE_POLL_SECONDS, backend.idle_timeout_s))
        backend.stop_if_idle()


def main() -> None:
    service = cfg.LLAMACPP_SERVICE

    parser = argparse.ArgumentParser(
        description="Lazy llama.cpp proxy: starts llama-server on the first request that needs it."
    )
    parser.add_argument("--port", type=int, default=service.port)
    parser.add_argument(
        "--idle-timeout-s",
        type=int,
        default=service.idle_timeout_s,
        help="Unload llama-server after this many seconds with nothing in flight.",
    )
    llamacpp.add_config_args(parser)
    args = parser.parse_args()

    conf = llamacpp.config_from_args(args, port=service.internal_port)
    backend = Backend(conf, args.idle_timeout_s)
    Handler.backend = backend

    threading.Thread(target=_watch_idle, args=(backend,), daemon=True).start()

    kill_processes_on_ports(args.port)
    print(f"[{TAG}] profile '{conf.name}' serves model id '{conf.alias}'")
    print(f"[{TAG}] starts on the first model request, unloads after {args.idle_timeout_s}s idle")

    serve_proxy(Handler, service.listen_ip, args.port, f"http://127.0.0.1:{conf.port}", TAG)


if __name__ == "__main__":
    main()
