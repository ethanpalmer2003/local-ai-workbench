"""Shared Silero endpointing, pre-roll and transport ownership for automatic ASR turns."""

import queue
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared.vad import Silero
from scripts.launchers.shared.transport.streaming_http import StreamingPost


class Turns:
    def __init__(
        self,
        base_url: str,
        log: Path,
        *,
        model="benchmark-asr",
        language="en-US",
        settings=cfg.AUDIOCPP_VAD,
        stream_factory=None,
        transport=None,
    ):
        self.transport = transport
        self.stream_factory = stream_factory
        self.url = (
            base_url.rstrip("/")
            + "/v1/audio/transcriptions/live?"
            + urlencode(
                {
                    "model": model,
                    "language": language,
                    "sample_rate": settings.sample_rate,
                    "channels": 1,
                    "sample_format": "s16le",
                }
            )
        )
        self.settings, self.vad = settings, Silero(log, settings)
        self.history = bytearray()
        self.samples = 0
        self.active: dict[str, Any] | None = None
        self.pending: list[dict[str, Any]] = []
        self.turn_id = 0

    def start(self):
        if self.transport:
            self.transport.start()
        self.vad.start()

    def push(self, frame: bytes):
        if len(frame) != self.settings.frame_samples * 2:
            raise ValueError("Expected one 512-sample PCM16 frame")
        self.samples += len(frame) // 2
        self.history.extend(frame)
        # Bounded history covers pre-roll plus helper scheduling delay.
        del self.history[: -self.settings.sample_rate * 4]
        self.vad.feed(frame)
        if self.active:
            self.active["stream"].send(frame)
        return self.poll()

    def _vad_event(self, event):
        kind = event["type"]
        if kind == "error":
            raise RuntimeError(event["error"])
        if kind == "speech_start":
            if self.active or len(self.pending) >= 2:
                raise RuntimeError("Turn capacity exceeded; preserve the current turn")
            start = max(0, event["sample"] - round(self.settings.sample_rate * self.settings.pre_roll_ms / 1000))
            available_start = self.samples - len(self.history) // 2
            if start < available_start:
                raise RuntimeError("VAD event arrived too late for retained pre-roll")
            stream = self.stream_factory() if self.stream_factory else StreamingPost(self.url)
            self.turn_id += 1
            turn = {"id": self.turn_id, "stream": stream, "start_sample": start, "end_reason": None}
            self.active = turn
            stream.start()
            stream.send(bytes(self.history[(start - available_start) * 2 :]))
        if kind == "speech_end" and self.active:
            self.active["end_reason"] = "silence"
            self.active["speech_end_sample"] = event["sample"]
            self.active["detected_at_sample"] = self.samples
            self.active["stream"].finish()
            self.pending.append(self.active)
            self.active = None
        return {**event, "received_samples": self.samples, "observed_at": time.perf_counter()}

    def _vad_events(self) -> list[dict[str, Any]]:
        events = []
        while True:
            try:
                events.append(self._vad_event(self.vad.events.get_nowait()))
            except queue.Empty:
                return events

    def _check_turn_length(self) -> None:
        if not self.active:
            return
        elapsed = (self.samples - self.active["start_sample"]) / self.settings.sample_rate
        if elapsed > self.settings.max_turn_seconds:
            raise RuntimeError("Maximum turn duration exceeded; explicit reset is required")

    def _drain_turn(self, events: list[dict[str, Any]], turn: dict[str, Any]) -> None:
        stream = turn["stream"]
        while True:
            try:
                item = stream.events.get_nowait()
            except queue.Empty:
                break
            if item.get("error") or item.get("type") == "error":
                raise RuntimeError(str(item))
            record = {**item, "turn_id": turn["id"], "observed_at": time.perf_counter()}
            if item.get("type") == "transcript.text.done":
                record.update(
                    end_reason=turn["end_reason"],
                    start_sample=turn["start_sample"],
                    speech_end_sample=turn.get("speech_end_sample"),
                    detected_at_sample=turn.get("detected_at_sample"),
                )
                stream.close()
                if turn in self.pending:
                    self.pending.remove(turn)
            events.append(record)
        if stream.done.is_set() and (turn in self.pending or turn is self.active):
            raise RuntimeError("ASR stream ended without a final transcript")

    def poll(self):
        events = self._vad_events()
        self._check_turn_length()
        for turn in [*self.pending, *([self.active] if self.active else [])]:
            self._drain_turn(events, turn)
        return events

    def close(self):
        try:
            for turn in [*self.pending, *([self.active] if self.active else [])]:
                turn["stream"].close()
        finally:
            try:
                self.vad.close()
            finally:
                if self.transport:
                    self.transport.close()
