"""Qwen3-ASR through llama.cpp, independent of the chat consumer."""

import json
import re
import subprocess
from typing import Any

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import requests
from scripts.launchers.shared.services import native


def url() -> str:
    return f"http://127.0.0.1:{cfg.QWEN3_ASR.port}"


def ready() -> bool:
    return launch_util.backend_ready(url() + "/health")


def command() -> list[str]:
    settings = cfg.QWEN3_ASR
    return [
        str(settings.exe),
        "-m",
        str(settings.model),
        "--mmproj",
        str(settings.mmproj),
        "--host",
        "127.0.0.1",
        "--port",
        str(settings.port),
        "--alias",
        "qwen3-asr",
        "--device",
        settings.device,
        "-ngl",
        "999",
        "-fa",
        "on",
        "-c",
        str(settings.context_size),
        "-np",
        "1",
        "-t",
        str(settings.threads),
        "-n",
        str(settings.max_tokens),
        "--jinja",
    ]


def matching_server() -> bool:
    return native.matches(command())


def start() -> subprocess.Popen[Any] | None:
    if launch_util.llama_server_running():
        print("Existing chat llama.cpp session retained; Qwen ASR uses its own port")
    settings = cfg.QWEN3_ASR
    return native.start_server(
        command(),
        (settings.exe, settings.model, settings.mmproj),
        settings.port,
        "Qwen ASR",
        ready,
        matching_server,
        component_key="asr/llamacpp",
    )


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
