"""Shared AudioCpp speech server lifecycle and file transcription adapter."""

import hashlib
import json
import queue
from pathlib import Path
from urllib.parse import urlencode

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import requests
from scripts.launchers.asr.shared.practice_models import tts_spec
from scripts.launchers.asr.shared.resident_profiles import audio_config
from scripts.launchers.audiocpp.tts_server import audio_environment
from scripts.launchers.shared.media.audio import decode_audio, mono_resample
from scripts.launchers.shared.services import native
from scripts.launchers.shared.transport.streaming_http import StreamingPost
from scripts.shared.wait import http_ready

# - The practice server hosts one ASR model plus TTS; the profile picks which recognizer
DEFAULT_ENGINE = "audiocpp-vulkan"
LABELS = {"audiocpp-vulkan": "Nemotron + AudioCpp TTS", "audiocpp-qwen3": "Qwen3 + AudioCpp TTS"}
# - the practice page names the engine it runs; the file profile names the recognizer behind it
ENGINE_PROFILES = {"audiocpp-nemotron": "audiocpp-vulkan"}


def profile_for(engine: str) -> str:
    """The AudioCpp recognizer profile a practice engine id runs."""
    return ENGINE_PROFILES.get(engine, engine)


def speech_config(port: int, engine: str = DEFAULT_ENGINE):
    config = audio_config(profile_for(engine), mode="streaming")
    config.update(lazy_load=False, max_loaded_models=2, idle_unload_ms=0, threads=5, port=port)

    config["models"].append(tts_spec())
    return config


def url() -> str:
    return native.service_url(cfg.AUDIOCPP_VAD.server_port)


def ready() -> bool:
    return native.service_ready(cfg.AUDIOCPP_VAD.server_port)


def command(port: int | None = None, engine: str = DEFAULT_ENGINE) -> list[str]:
    port = cfg.AUDIOCPP_VAD.server_port if port is None else port
    text = json.dumps(speech_config(port, engine), indent=2)
    folder = project_cfg.component("audiocpp").generated_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"asr-tts-{hashlib.sha256(text.encode()).hexdigest()[:12]}.json"
    path.write_text(text, encoding="utf-8")
    return [str(project_cfg.AUDIOCPP_SERVER_EXE), "--config", str(path), "--port", str(port), "--no-ui"]


def start(port: int | None = None, engine: str = DEFAULT_ENGINE):
    port = cfg.AUDIOCPP_VAD.server_port if port is None else port
    argv = command(port, engine)
    return native.start_server(
        argv,
        [project_cfg.AUDIOCPP_SERVER_EXE, *(Path(m["path"]) for m in speech_config(port, engine)["models"])],
        port,
        LABELS.get(profile_for(engine), LABELS[DEFAULT_ENGINE]),
        lambda: http_ready(f"http://127.0.0.1:{port}/health"),
        lambda: native.matches(argv),
        env=audio_environment(),
        component_key="audiocpp",
    )


def _validated(request: requests.AudioRequest) -> None:
    if request.suppress_non_speech:
        raise ValueError("Non-speech token suppression is a Whisper-specific option")
    if request.response_format not in ("json", "text"):
        raise ValueError("AudioCpp speech models support json or text output")


def _pcm(request: requests.AudioRequest) -> bytes:

    samples, rate = decode_audio(request.audio)
    pcm = (mono_resample(samples, rate).clip(-1, 1) * 32767).astype("<i2").tobytes()
    if not pcm or len(pcm) > 16000 * 2 * 30:
        raise ValueError("AudioCpp speech uploads must contain 0-30 seconds of audio")
    return pcm


def _stream_url(request: requests.AudioRequest) -> str:
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


def _await_transcript(stream: StreamingPost, response_format: str) -> tuple[bytes, str]:
    while True:
        try:
            event = stream.events.get(timeout=1)
        except queue.Empty:
            if stream.done.is_set():
                raise RuntimeError("AudioCpp stream ended without a final transcript") from None
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
