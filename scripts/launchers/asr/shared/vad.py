"""AudioCpp's native Silero CPU helper: one continuous, stateful 16 kHz stream."""

import queue
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg, launch_util
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.services.process import stop_owned


def command(settings=cfg.AUDIOCPP_VAD):
    return [
        str(project_cfg.AUDIOCPP_SERVER_EXE.with_name("audiocpp_cli.exe")),
        "--family",
        "silero_vad",
        "--task",
        "vad",
        "--model",
        str(settings.model),
        "--backend",
        "cpu",
        "--threads",
        "1",
        "--mode",
        "streaming",
        "--audio",
        "-",
        "--input-format",
        "s16le",
        "--input-rate",
        str(settings.sample_rate),
        "--input-channels",
        "1",
        "--session-option",
        f"threshold={settings.threshold}",
        "--session-option",
        f"min_silence_duration_ms={settings.silence_ms}",
        "--session-option",
        "speech_pad_ms=0",
    ]


def parse_event(line: str):
    match = re.fullmatch(
        r"event=(speech_start|speech_end|speech_segment) sample=(\d+) probability=([\d.eE+-]+)", line.strip()
    )
    return {"type": match[1], "sample": int(match[2]), "probability": float(match[3])} if match else None


class Silero:
    def __init__(self, log: Path, settings=cfg.AUDIOCPP_VAD):
        self.log, self.settings = log, settings
        self.process: subprocess.Popen[bytes] | None = None
        self.reader: threading.Thread | None = None
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stream = None
        self.transcript = None
        self.ready = threading.Event()

    def start(self):
        require_native_execution("AudioCpp Silero VAD")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.log.open("wb")
        self.transcript = self.log.with_suffix(".stdout.log").open("wb")
        self.process = subprocess.Popen(
            command(self.settings), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stream
        )
        launch_util.assign_process_to_job(self.process.pid)
        source = self.process.stdout
        assert source is not None

        def read():
            for data in source:
                if self.transcript:
                    self.transcript.write(data)
                    self.transcript.flush()
                line = data.decode(errors="replace").strip()
                if line.startswith("audio_input=stdin"):
                    self.ready.set()
                event = parse_event(line)
                if event:
                    self.events.put(event)
            self.events.put({"type": "error", "error": "VAD helper exited"})

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        if not self.ready.wait(15):
            self.close()
            raise RuntimeError(f"VAD did not become ready; inspect {self.log}")

    def feed(self, frame: bytes):
        if len(frame) != self.settings.frame_samples * 2:
            raise ValueError("Silero requires exactly 512 mono PCM16 samples per frame")
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError("VAD helper is not running")
        self.process.stdin.write(frame)
        self.process.stdin.flush()

    def close(self):
        if self.process:
            if self.process.stdin and not self.process.stdin.closed:
                try:
                    self.process.stdin.close()
                    self.process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            stop_owned(self.process, timeout=2)
        if self.reader:
            self.reader.join(timeout=1)
        if self.stream:
            self.stream.close()
        if self.transcript:
            self.transcript.close()
