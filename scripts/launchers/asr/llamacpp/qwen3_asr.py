"""Qwen3-ASR through llama.cpp, independent of the chat consumer."""

import json
import re
import subprocess
from typing import Any

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.llamacpp.llama_audio import LlamaAudioBackend
from scripts.launchers.asr.shared import requests

BACKEND = LlamaAudioBackend(cfg.QWEN3_ASR, alias="qwen3-asr", label="Qwen ASR", device=cfg.QWEN3_ASR.device)


def url() -> str:
    return BACKEND.url()


def ready() -> bool:
    return BACKEND.ready()


def command() -> list[str]:
    return BACKEND.command()


def matching_server() -> bool:
    return BACKEND.matching_server()


def start() -> subprocess.Popen[Any] | None:
    return BACKEND.start(ready, matching_server)


def clean_transcript(text: str) -> str:
    text = re.sub(r"^\s*language\s+[^<\r\n]+<asr_text>", "", text)
    return text.removeprefix("<asr_text>").strip()


def transcribe(body: bytes, content_type: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    request = requests.parse(body, content_type)
    if request.suppress_non_speech:
        raise ValueError("Non-speech token suppression is a Whisper-specific option; disable it for Qwen ASR")
    body, content_type = requests.multipart_body(body, content_type)
    data, response_type = requests.post(url() + "/v1/audio/transcriptions", body, content_type, headers)
    if "application/json" in response_type:
        result = json.loads(data)
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise RuntimeError("Qwen ASR returned no transcription text")
        result["text"] = clean_transcript(result["text"])
        return json.dumps(result).encode(), response_type
    if response_type.startswith("text/plain"):
        return clean_transcript(data.decode()).encode(), response_type
    return data, response_type
