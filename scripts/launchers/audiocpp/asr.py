"""Shared Nemotron/Kokoro server lifecycle and file transcription adapter."""

import hashlib
import json
import queue
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import requests
from scripts.launchers.asr.shared.resident_profiles import audio_config
from scripts.launchers.audiocpp.kokoro import audio_environment
from scripts.launchers.shared.services import native
from scripts.launchers.shared.services.process import http_ready
from scripts.launchers.shared.transport.streaming_http import StreamingPost


def speech_config(port: int):
    config = audio_config("audiocpp-vulkan", mode="streaming")
    config.update(lazy_load=False, max_loaded_models=2, idle_unload_ms=0, threads=5, port=port)
    from scripts.launchers.asr.shared.practice_models import tts_spec

    config["models"].append(tts_spec())
    return config


def url() -> str:
    return f"http://127.0.0.1:{cfg.AUDIOCPP_VAD.server_port}"


def ready() -> bool:
    return http_ready(url() + "/health")


def command(port: int | None = None) -> list[str]:
    port = cfg.AUDIOCPP_VAD.server_port if port is None else port
    text = json.dumps(speech_config(port), indent=2)
    folder = project_cfg.component("audiocpp").generated_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"asr-kokoro-{hashlib.sha256(text.encode()).hexdigest()[:12]}.json"
    path.write_text(text, encoding="utf-8")
    return [str(project_cfg.AUDIOCPP_SERVER_EXE), "--config", str(path), "--port", str(port), "--no-ui"]


def start(port: int | None = None):
    port = cfg.AUDIOCPP_VAD.server_port if port is None else port
    argv = command(port)
    return native.start_server(
        argv,
        [
            project_cfg.AUDIOCPP_SERVER_EXE,
            cfg.AUDIOCPP_VAD.model,
            *(Path(m["path"]) for m in speech_config(port)["models"]),
        ],
        port,
        "Nemotron + Kokoro AudioCpp",
        lambda: http_ready(f"http://127.0.0.1:{port}/health"),
        lambda: native.matches(argv),
        env=audio_environment(),
        component_key="audiocpp",
    )


def _validated(request: Any) -> None:
    if request.suppress_non_speech:
        raise ValueError("Non-speech token suppression is a Whisper-specific option")
    if request.response_format not in ("json", "text"):
        raise ValueError("Nemotron supports json or text output")


def _pcm(request: Any) -> bytes:
    from scripts.launchers.shared.media.audio import decode_audio, mono_resample

    samples, rate = decode_audio(request.audio)
    pcm = (mono_resample(samples, rate).clip(-1, 1) * 32767).astype("<i2").tobytes()
    if not pcm or len(pcm) > 16000 * 2 * 30:
        raise ValueError("Nemotron uploads must contain 0-30 seconds of audio")
    return pcm


def _stream_url(request: Any) -> str:
    query = urlencode(
        {
            "model": "benchmark-asr",
            "language": request.language,
            "sample_rate": 16000,
            "channels": 1,
            "sample_format": "s16le",
        }
    )
    return url() + "/v1/audio/transcriptions/live?" + query


def _await_transcript(stream: Any, response_format: str) -> tuple[bytes, str]:
    while True:
        try:
            event = stream.events.get(timeout=1)
        except queue.Empty:
            if stream.done.is_set():
                raise RuntimeError("Nemotron upload ended without a final transcript")
            continue
        if event.get("error") or event.get("type") == "error":
            raise RuntimeError(str(event))
        if event.get("type") == "transcript.text.done":
            text = event.get("text")
            if not isinstance(text, str):
                raise RuntimeError("Nemotron returned no text")
            if response_format == "text":
                return text.encode(), "text/plain"
            return json.dumps({"text": text}).encode(), "application/json"


def transcribe(body: bytes, content_type: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    request = requests.parse(body, content_type)
    _validated(request)
    pcm = _pcm(request)
    # The configured model is streaming; file uploads must use its live transport too.
    stream = StreamingPost(_stream_url(request), timeout=30)
    try:
        stream.start()
        for offset in range(0, len(pcm), 32768):
            stream.send(pcm[offset : offset + 32768])
        stream.finish()
        return _await_transcript(stream, request.response_format)
    finally:
        stream.close()
