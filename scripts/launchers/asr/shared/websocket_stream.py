"""Persistent local WebSocket bridge; normalize NeMo events for shared ASR turns."""

import base64
import json
import queue
import subprocess
import threading
from pathlib import Path

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.services.process import stop_owned


class WebSocketBridge:
    def __init__(self, url: str, language: str, log: Path):
        self.url, self.language, self.log = url, language, log
        self.process = None
        self.reader = None
        self.stderr = None
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.streams = {}
        self.serial = 0

    def start(self):
        require_native_execution("NeMo WebSocket transport")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.stderr = self.log.open("wb")
        worker = Path(__file__).parents[2] / "shared/websocket_worker.mjs"
        self.process = subprocess.Popen(
            [cfg.PI_CLIENT.node_cmd, str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr
        )
        launch_util.assign_process_to_job(self.process.pid)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        if not self.ready.wait(10):
            self.close()
            raise RuntimeError("WebSocket helper did not become ready")

    def _read(self):
        assert self.process and self.process.stdout
        try:
            for line in self.process.stdout:
                if len(line) > 1048576:
                    raise RuntimeError("WebSocket helper event exceeds limit")
                item = json.loads(line)
                if item.get("type") == "ready":
                    self.ready.set()
                with self.lock:
                    stream = self.streams.get(item.get("id"))
                if stream:
                    stream.receive(item)
        finally:
            with self.lock:
                for stream in self.streams.values():
                    stream.events.put({"type": "error", "error": "WebSocket helper exited"})
                    stream.done.set()

    def send(self, item):
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError("WebSocket helper is not running")
        self.process.stdin.write(json.dumps(item).encode() + b"\n")
        self.process.stdin.flush()

    def stream(self):
        with self.lock:
            if len(self.streams) >= 2:
                raise RuntimeError("WebSocket turn capacity exceeded")
            self.serial += 1
            stream = WebSocketStream(self, self.serial)
            self.streams[self.serial] = stream
            return stream

    def close(self):
        if self.process:
            stop_owned(self.process, timeout=2)
        if self.reader:
            self.reader.join(timeout=2)
        if self.stderr:
            self.stderr.close()


class WebSocketStream:
    def __init__(self, bridge: WebSocketBridge, identity: int):
        self.bridge, self.id = bridge, identity
        self.events = queue.Queue()
        self.ready, self.done = threading.Event(), threading.Event()

    def receive(self, item):
        event = item.get("event", item)
        kind = event.get("type", "")
        if kind == "session.updated":
            self.ready.set()
        elif kind.endswith("input_audio_transcription.completed"):
            self.events.put({"type": "transcript.text.done", "text": event.get("transcript", "")})
            self.done.set()
        elif kind.endswith("input_audio_transcription.delta"):
            self.events.put({"type": "transcript.text.delta", "delta": event.get("delta", "")})
        elif kind in ("error", "closed"):
            self.events.put({"type": "error", "error": event.get("error", event.get("message", "WebSocket closed"))})
            self.done.set()
            self.ready.set()

    def start(self):
        self.bridge.send(
            {
                "op": "open",
                "id": self.id,
                "url": self.bridge.url,
                "session": {"sample_rate": 16000, "language": self.bridge.language, "endpointing_ms": 10000},
            }
        )
        if not self.ready.wait(5) or self.done.is_set():
            raise RuntimeError("NeMo streaming session did not become ready")

    def send(self, frame: bytes):
        self.bridge.send({"op": "audio", "id": self.id, "audio": base64.b64encode(frame).decode()})

    def finish(self):
        self.bridge.send({"op": "commit", "id": self.id})

    def close(self):
        with self.bridge.lock:
            self.bridge.streams.pop(self.id, None)
        if self.bridge.process and self.bridge.process.poll() is None:
            self.bridge.send({"op": "close", "id": self.id})
