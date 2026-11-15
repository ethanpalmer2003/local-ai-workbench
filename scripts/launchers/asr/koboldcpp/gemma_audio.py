"""Gemma audio using the same loaded Kobold model for transcription and chat."""

import subprocess
from typing import Any

import requests

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.llamacpp import gemma_audio


def url() -> str:
    return f"http://127.0.0.1:{cfg.KOBOLDCPP_KCPPS_ARGS['port']}"


def ready() -> bool:
    try:
        response = requests.get(url() + "/api/extra/version", timeout=2)
        response.raise_for_status()
    except requests.RequestException:
        return False
    capabilities = response.json()
    return bool(capabilities.get("audio") and capabilities.get("llm"))


def command() -> list[str]:
    return []


def start() -> subprocess.Popen[Any] | None:
    if cfg.kobold_chat_model_path() != cfg.GEMMA_AUDIO_ASR.model:
        raise ValueError("Gemma audio needs the matching Gemma 4 E4B chat model")
    if not cfg.GEMMA_AUDIO_ASR.mmproj.is_file():
        raise FileNotFoundError(f"Missing Gemma multimodal projector: {cfg.GEMMA_AUDIO_ASR.mmproj}")
    return None


def matching_server() -> bool:
    return ready()


def transcribe(body: bytes, content_type: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    return gemma_audio.transcribe(body, content_type, headers, url())
