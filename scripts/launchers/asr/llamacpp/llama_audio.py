"""Shared llama.cpp audio-server plumbing for the ASR consumers."""

import subprocess
from collections.abc import Callable
from typing import Any

from scripts.launchers import launch_util
from scripts.launchers.shared.services import native
from scripts.shared.wait import http_ready

COMPONENT_KEY = "asr/llamacpp"


class LlamaAudioBackend:
    """One llama.cpp audio server described by the settings it starts from."""

    def __init__(self, settings: Any, *, alias: str, label: str, device: str) -> None:
        self.settings = settings
        self.alias = alias
        self.label = label
        self.device = device

    def url(self) -> str:
        return f"http://127.0.0.1:{self.settings.port}"

    def ready(self) -> bool:
        return http_ready(self.url() + "/health", strict=True)

    def command(self) -> list[str]:
        settings = self.settings
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
            self.alias,
            "--device",
            self.device,
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

    def matching_server(self) -> bool:
        return native.matches(self.command())

    def start(self, ready: Callable[[], bool], matching: Callable[[], bool]) -> subprocess.Popen[Any] | None:
        if launch_util.llama_server_running():
            print(f"Existing llama.cpp chat session retained; {self.label} uses its configured port")
        settings = self.settings
        return native.start_server(
            self.command(),
            (settings.exe, settings.model, settings.mmproj),
            settings.port,
            self.label,
            ready,
            matching,
            component_key=COMPONENT_KEY,
        )
