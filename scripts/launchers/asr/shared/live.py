"""Bounded microphone sessions shared by both practice gateways.

PCM uploads and polling serialize access to Turns. Stop, idle expiry and gateway
shutdown own cleanup; no helper starts until the user starts listening.
"""

import json
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from scripts.config import project_config as project_cfg
from scripts.config.shared import speech_delivery
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector
from scripts.launchers.asr.shared.segment_stream import SegmentStream
from scripts.launchers.asr.shared.turns import Turns
from scripts.launchers.asr.shared.websocket_stream import WebSocketBridge
from scripts.launchers.proxy_util import read_request_body, send_bytes, send_json_error


class Sessions:
    def __init__(self, engine: cfg.AsrStartupEngine = cfg.AsrStartupEngine.AUDIOCPP):
        self.engine = engine
        self.lock = threading.Lock()
        self.turns = None
        self.token = ""
        self.touched = 0.0
        self.closed = threading.Event()
        self.reaper = threading.Thread(target=self._expire, daemon=True)
        self.reaper.start()

    def _drop(self):
        turns, self.turns = self.turns, None
        self.token = ""
        if turns:
            turns.close()

    def reset(self, engine):
        with self.lock:
            self._drop()
            self.engine = engine

    def _expire(self):
        while not self.closed.wait(5):
            with self.lock:
                if self.turns and time.monotonic() - self.touched > 30:
                    self._drop()

    def close(self):
        self.closed.set()
        with self.lock:
            self._drop()
        self.reaper.join(timeout=6)

    def request(self, path: str, body: bytes) -> dict[str, Any]:
        with self.lock:
            if self.closed.is_set():
                raise ValueError("Practice gateway is closing")
            if path == "/asr/live/start":
                if self.turns:
                    raise ValueError("Already listening; stop the other microphone session first")
                language = json.loads(body).get("language", "auto")
                from scripts.launchers.asr.shared.languages import capabilities

                allowed = capabilities(self.engine)["asr"]["ready_languages"]
                if language != "auto" and language not in allowed:
                    raise ValueError("Choose a language supported by the selected ASR model")
                folder = project_cfg.component("audiocpp").logs_dir
                folder.mkdir(parents=True, exist_ok=True)
                streaming = speech_delivery.asr_plan(self.engine.value)["mode"] == "streaming"
                factory = (
                    None
                    if streaming
                    and self.engine in (cfg.AsrStartupEngine.AUDIOCPP, cfg.AsrStartupEngine.PARAKEET_STREAM)
                    else lambda: SegmentStream(selector.backend(self.engine), language)
                )
                transport = None
                if streaming and self.engine == cfg.AsrStartupEngine.NEMO:
                    transport = WebSocketBridge(
                        selector.backend(self.engine).url().replace("http://", "ws://")
                        + "/v1/audio/transcriptions/realtime",
                        language,
                        project_cfg.component("asr/nemo-speechcpp").logs_dir / f"websocket-{time.time_ns()}.log",
                    )
                    factory = transport.stream
                turns = Turns(
                    selector.backend(self.engine).url(),
                    folder / f"silero-{time.time_ns()}.log",
                    language=language,
                    stream_factory=factory,
                    transport=transport,
                )
                try:
                    turns.start()
                except Exception:
                    turns.close()
                    raise
                self.turns, self.token = turns, uuid.uuid4().hex
                self.touched = time.monotonic()
                return {"session": self.token, "sample_rate": 16000, "frame_samples": 512}
            if not self.turns or path not in (f"/asr/live/{self.token}/audio", f"/asr/live/{self.token}/stop"):
                raise ValueError("Microphone session expired or was stopped")
            self.touched = time.monotonic()
            if path.endswith("/stop"):
                self._drop()
                return {"events": []}
            if len(body) % 1024:
                raise ValueError("Audio must contain complete 512-sample PCM16 frames")
            try:
                events = []
                for offset in range(0, len(body), 1024):
                    events.extend(self.turns.push(body[offset : offset + 1024]))
                events.extend(self.turns.poll())
                return {"events": events}
            except Exception:
                self._drop()
                raise

    def route(self, handler, method: str, path: str, engine: cfg.AsrStartupEngine) -> bool:
        if not path.startswith("/asr/live/"):
            return False
        if not supported(engine) or method != "POST":
            send_json_error(
                handler, 400, "This recognizer does not have automatic turns; POST is required", "invalid_request_error"
            )
            return True
        # Browsers must use this gateway's origin; never let another website start a native helper.
        origin = handler.headers.get("Origin")
        if origin and urlsplit(origin).netloc != handler.headers.get("Host"):
            send_json_error(handler, 403, "Use the practice page on this server", "invalid_request_error")
            return True
        try:
            length = int(handler.headers.get("Content-Length", "0"))
            if not 0 <= length <= 32768:
                raise ValueError("Microphone request exceeds one second of audio")
            result = self.request(path, read_request_body(handler))
            send_bytes(handler, 200, json.dumps(result).encode(), "application/json")
        except (ValueError, TypeError, AttributeError) as error:
            send_json_error(handler, 400, str(error), "invalid_request_error")
        except (RuntimeError, OSError) as error:
            send_json_error(handler, 502, str(error), "backend_response_error")
        return True


def capable(engine: cfg.AsrStartupEngine) -> bool:
    return engine.value in speech_delivery.ASR_CHUNKED


def supported(engine: cfg.AsrStartupEngine) -> bool:
    return speech_delivery.asr_plan(engine.value)["mode"] != "whole"
