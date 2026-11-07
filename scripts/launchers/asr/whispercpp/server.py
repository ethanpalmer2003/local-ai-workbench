"""Standalone Vulkan Whisper lifecycle and shared transcription requests."""

import subprocess
from pathlib import Path
from typing import Any

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import requests
from scripts.launchers.shared.services import native


def url() -> str:
    return f"http://127.0.0.1:{cfg.WHISPERCPP_ASR.port}"


def ready() -> bool:
    return launch_util.backend_ready(url() + "/health")


def server_command(
    exe: Path, model: Path, port: int, threads: int, device: int | str, flash_attention: bool, language: str
) -> list[str]:
    return [
        str(exe),
        "-m",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "-t",
        str(threads),
        "-p",
        "1",
        "-dev",
        str(device),
        "-fa" if flash_attention else "-nfa",
        "-l",
        language,
        "-bo",
        "-1",
        "-bs",
        "-1",
        "-ml",
        "100",
        "-sow",
        "-nt",
    ]


def command() -> list[str]:
    settings = cfg.WHISPERCPP_ASR
    return server_command(
        settings.exe,
        settings.model,
        settings.port,
        settings.threads,
        settings.device,
        settings.flash_attention,
        settings.language,
    )


def matching_server() -> bool:
    return native.matches(command())


def start() -> subprocess.Popen[Any] | None:
    settings = cfg.WHISPERCPP_ASR
    return native.start_server(
        command(),
        (settings.exe, settings.model),
        settings.port,
        "Whisper Vulkan",
        ready,
        matching_server,
        60,
        component_key="asr/whispercpp",
    )


def transcription_body(body: bytes, content_type: str) -> tuple[bytes, str]:
    return requests.multipart_body(body, content_type, cfg.WHISPERCPP_ASR.language)


def transcribe(body: bytes, content_type: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    body, content_type = transcription_body(body, content_type)
    return requests.post(url() + "/inference", body, content_type, headers)
