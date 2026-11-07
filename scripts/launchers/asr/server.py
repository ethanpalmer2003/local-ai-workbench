"""ASR API gateway with optional llama.cpp chat forwarding."""

import argparse
import json
import threading
from contextlib import nullcontext
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
    restart_requested = False

    class Handler(ProxyHandlerMixin):
        protocol_version = "HTTP/1.1"

        def _forward(self, method: str) -> None:
            path = urlsplit(self.path).path
            origin = self.headers.get("Origin") if runtime else None
            if runtime and method == "POST" and origin and urlsplit(origin).netloc != self.headers.get("Host"):
                send_json_error(self, 403, "Use this workspace origin", "invalid_request_error")
                return
            try:
                with controls.request() if controls else nullcontext():
                    stage = runtime.stage_for(method, path) if runtime else None
                    with (
                        runtime.lifecycle.use(stage, "session_open" if path == "/asr/live/start" else "request")
                        if runtime
                        else nullcontext()
                    ):
                        self._route_request(method)
            except (RuntimeError, OSError, TimeoutError) as error:
                send_json_error(self, 503, str(error), "service_start_error")

        # ProxyHandlerMixin owns _dispatch; overriding it bypasses request/lifecycle guards.
        def _route_request(self, method: str) -> None:
            nonlocal restart_requested
            path = urlsplit(self.path).path
            selected_engine = runtime.controls.engine if runtime else engine
            speech_url = runtime.speech_url() if runtime else speech_upstream
            chat_url = runtime.chat_url() if runtime else chat_upstream
            if speech_ui.route(self, method, runtime):
                return
            if runtime and path == "/workspace/restart":
                if method != "POST":
                    send_json_error(self, 405, "Use POST", "invalid_request_error")
                    return
                send_bytes(self, 202, b'{"restarting":true}', "application/json")
                restart_requested = True
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if runtime and method == "GET" and path == "/":
                http_api.static_get(self, "/practice", selected_engine, "llama.cpp", True)
                return
            if runtime and lifecycle_http.route(self, method, path, runtime, sessions):
                return
            if runtime and delivery.route(self, method, path, controls):
                return
            if path == "/practice/models" and controls:
                try:
                    if method == "GET":
                        send_bytes(self, 200, json.dumps(controls.catalog()).encode(), "application/json")
                    elif method == "POST":
                        selection = controls.select(json.loads(read_request_body(self)))
                        send_bytes(self, 202, json.dumps({"switching": selection}).encode(), "application/json")
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                    else:
                        send_json_error(self, 405, "Use GET or POST", "invalid_request_error")
                except (ValueError, TypeError) as error:
                    send_json_error(self, 400, str(error), "invalid_request_error")
                except RuntimeError as error:
                    send_json_error(self, 409, str(error), "busy")
                return
            if sessions.route(self, method, path, selected_engine):
                return
            if method == "GET" and http_api.static_get(
                self,
                path,
                selected_engine,
                "llama.cpp" if chat_url else "none",
                bool(runtime),
                runtime.llm_path().name if runtime else None,
                runtime.chat_url() + "/" if runtime else None,
                delivery.plans(controls) if runtime else None,
            ):
                return
            if method == "GET" and path == "/health":
                send_bytes(
                    self,
                    200 if runtime or selector.backend(selected_engine).ready() else 503,
                    b'{"service":"asr"}',
                    "application/json",
                )
                return
            body = read_request_body(self)
            if method == "POST" and path in ("/v1/audio/transcriptions", "/api/extra/transcribe"):
                http_api.transcribe(self, body, selected_engine)
            elif method == "GET" and path == "/proxy/speech-models" and speech_url:
                relay_stream(
                    self,
                    method,
                    speech_url + "/v1/models" + self.path.removeprefix(path),
                    build_forward_headers(self.headers, body),
                    body,
                    "tts",
                )
            elif path == "/v1/audio/speech" and speech_url:
                try:
                    payload = json.loads(body)
                    if not isinstance(payload, dict) or not isinstance(payload.get("options", {}), dict):
                        raise ValueError("Speech request and options must be JSON objects")
                    payload = practice_models.speech_body(payload)
                except (ValueError, TypeError) as error:
                    send_json_error(self, 400, str(error), "invalid_request_error")
                    return
                body = json.dumps(payload).encode()
                relay_stream(
                    self,
                    method,
                    speech_url + self.path,
                    build_forward_headers(self.headers, body),
                    body,
                    "tts",
                    response_headers=streamed_speech_response_headers(payload),
                )
            elif chat_url:
                relay_stream(
                    self, method, chat_url + self.path, build_forward_headers(self.headers, body), body, "llama-chat"
                )
            else:
                send_bytes(self, 404, b'{"error":"ASR service has no chat upstream"}', "application/json")

    try:
        serve_proxy(Handler, host, port, chat_upstream or selector.backend(engine).url(), "asr", on_server)
    finally:
        sessions.close()
    return restart_requested


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
