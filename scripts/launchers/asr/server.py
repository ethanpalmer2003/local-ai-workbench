"""ASR API gateway with optional llama.cpp chat forwarding."""

import argparse
import json
import threading
from contextlib import nullcontext
from typing import Any, ClassVar
from urllib.parse import urlsplit

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector
from scripts.launchers.asr.shared import delivery, http_api, lifecycle_http, live, practice_models
from scripts.launchers.llamacpp import speech_ui
from scripts.launchers.proxy_util import (
    ProxyHandlerMixin,
    build_forward_headers,
    read_request_body,
    relay_stream,
    send_bytes,
    send_json_error,
    serve_proxy,
    streamed_speech_response_headers,
)


class _AsrProxyHandler(ProxyHandlerMixin):
    protocol_version = "HTTP/1.1"
    # - set by run_proxy on the per-run subclass
    engine: ClassVar[Any]
    runtime: ClassVar[Any] = None
    controls: ClassVar[Any] = None
    sessions: ClassVar[Any] = None
    chat_upstream: ClassVar[str | None] = None
    speech_upstream: ClassVar[str | None] = None
    restart_requested: ClassVar[bool] = False

    def _forward(self, method: str) -> None:
        path = urlsplit(self.path).path
        origin = self.headers.get("Origin") if self.runtime else None
        if self.runtime and method == "POST" and origin and urlsplit(origin).netloc != self.headers.get("Host"):
            send_json_error(self, 403, "Use this workspace origin", "invalid_request_error")
            return
        try:
            with self.controls.request() if self.controls else nullcontext():
                stage = self.runtime.stage_for(method, path) if self.runtime else None
                with (
                    self.runtime.lifecycle.use(stage, "session_open" if path == "/asr/live/start" else "request")
                    if self.runtime
                    else nullcontext()
                ):
                    self._route_request(method)
        except (RuntimeError, OSError, TimeoutError) as error:
            send_json_error(self, 503, str(error), "service_start_error")

    # ProxyHandlerMixin owns _dispatch; overriding it bypasses request/lifecycle guards.
    def _route_request(self, method: str) -> None:
        path = urlsplit(self.path).path
        selected_engine = self.runtime.controls.engine if self.runtime else self.engine
        speech_url = self.runtime.speech_url() if self.runtime else self.speech_upstream
        chat_url = self.runtime.chat_url() if self.runtime else self.chat_upstream
        if speech_ui.route(self, method, self.runtime):
            return
        if self._runtime_routes(method, path, selected_engine):
            return
        if self._practice_models(method, path):
            return
        if self.sessions.route(self, method, path, selected_engine):
            return
        if self._static_get(method, path, selected_engine, chat_url):
            return
        self._relay(method, path, selected_engine, speech_url, chat_url)

    def _runtime_routes(self, method: str, path: str, selected_engine: cfg.AsrStartupEngine) -> bool:
        if not self.runtime:
            return False
        if path == "/workspace/restart":
            if method != "POST":
                send_json_error(self, 405, "Use POST", "invalid_request_error")
                return True
            send_bytes(self, 202, b'{"restarting":true}', "application/json")
            type(self).restart_requested = True
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return True
        if method == "GET" and path == "/":
            http_api.static_get(self, "/practice", selected_engine, "llama.cpp", True)
            return True
        return bool(
            lifecycle_http.route(self, method, path, self.runtime, self.sessions)
            or delivery.route(self, method, path, self.controls)
        )

    def _practice_models(self, method: str, path: str) -> bool:
        if path != "/practice/models" or not self.controls:
            return False
        try:
            if method == "GET":
                send_bytes(self, 200, json.dumps(self.controls.catalog()).encode(), "application/json")
            elif method == "POST":
                selection = self.controls.select(json.loads(read_request_body(self)))
                send_bytes(self, 202, json.dumps({"switching": selection}).encode(), "application/json")
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                send_json_error(self, 405, "Use GET or POST", "invalid_request_error")
        except (ValueError, TypeError) as error:
            send_json_error(self, 400, str(error), "invalid_request_error")
        except RuntimeError as error:
            send_json_error(self, 409, str(error), "busy")
        return True

    def _static_get(self, method: str, path: str, selected_engine: cfg.AsrStartupEngine, chat_url: str | None) -> bool:
        if method == "GET" and path == "/health":
            ready = bool(self.runtime) or selector.backend(selected_engine).ready()
            send_bytes(self, 200 if ready else 503, b'{"service":"asr"}', "application/json")
            return True
        return method == "GET" and bool(
            http_api.static_get(
                self,
                path,
                selected_engine,
                "llama.cpp" if chat_url else "none",
                bool(self.runtime),
                self.runtime.llm_path().name if self.runtime else None,
                self.runtime.chat_url() + "/" if self.runtime else None,
                delivery.plans(self.controls) if self.runtime else None,
            )
        )

    def _relay(
        self,
        method: str,
        path: str,
        selected_engine: cfg.AsrStartupEngine,
        speech_url: str | None,
        chat_url: str | None,
    ) -> None:
        body = read_request_body(self)
        if method == "POST" and path in ("/v1/audio/transcriptions", "/api/extra/transcribe"):
            http_api.transcribe(self, body, selected_engine)
            return
        if method == "GET" and path == "/proxy/speech-models" and speech_url:
            relay_stream(
                self,
                method,
                speech_url + "/v1/models" + self.path.removeprefix(path),
                build_forward_headers(self.headers, body),
                body,
                "tts",
            )
            return
        if path == "/v1/audio/speech" and speech_url:
            self._relay_speech(method, body, speech_url)
            return
        if chat_url:
            relay_stream(
                self, method, chat_url + self.path, build_forward_headers(self.headers, body), body, "llama-chat"
            )
            return
        send_bytes(self, 404, b'{"error":"ASR service has no chat upstream"}', "application/json")

    def _relay_speech(self, method: str, body: bytes, speech_url: str) -> None:
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("options", {}), dict):
                raise ValueError("Speech request and options must be JSON objects")
            payload = practice_models.speech_body(payload)
        except (ValueError, TypeError) as error:
            send_json_error(self, 400, str(error), "invalid_request_error")
            return
        encoded = json.dumps(payload).encode()
        relay_stream(
            self,
            method,
            speech_url + self.path,
            build_forward_headers(self.headers, encoded),
            encoded,
            "tts",
            response_headers=streamed_speech_response_headers(payload),
        )


def run_proxy(
    engine: cfg.AsrStartupEngine,
    host: str,
    port: int,
    chat_upstream: str | None = None,
    speech_upstream: str | None = None,
    on_server=None,
    controls=None,
    runtime=None,
) -> bool:
    sessions = live.Sessions(engine)
    handler = type(
        "Handler",
        (_AsrProxyHandler,),
        {
            "engine": engine,
            "runtime": runtime,
            "controls": controls,
            "sessions": sessions,
            "chat_upstream": chat_upstream,
            "speech_upstream": speech_upstream,
        },
    )
    try:
        serve_proxy(handler, host, port, chat_upstream or selector.backend(engine).url(), "asr", on_server)
    finally:
        sessions.close()
    return bool(handler.restart_requested)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine",
        choices=[
            item.value
            for item in cfg.AsrStartupEngine
            if item not in (cfg.AsrStartupEngine.EMBEDDED, cfg.AsrStartupEngine.GEMMA_KOBOLD)
        ],
        default=cfg.ASR_SERVICE.engine.value,
    )
    parser.add_argument("--port", type=int, default=cfg.ASR_SERVICE.port)
    args = parser.parse_args()
    engine = cfg.AsrStartupEngine(args.engine)
    process = selector.backend(engine).start()
    try:
        run_proxy(engine, cfg.ASR_SERVICE.host, args.port)
    except KeyboardInterrupt:
        pass
    finally:
        if process is not None and process.poll() is None:
            launch_util.kill_process_tree(process.pid)
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
