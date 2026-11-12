"""Qwen3-ASR 1.7B served by the shared practice AudioCpp server."""

from scripts.launchers.audiocpp import asr

ENGINE = "audiocpp-qwen3"


def speech_config(port: int):
    return asr.speech_config(port, ENGINE)


def url() -> str:
    return asr.url()


def ready() -> bool:
    return asr.ready()


def command(port: int | None = None) -> list[str]:
    return asr.command(port, ENGINE)


def start(port: int | None = None):
    return asr.start(port, ENGINE)


def transcribe(body: bytes, content_type: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    return asr.transcribe(body, content_type, headers)
