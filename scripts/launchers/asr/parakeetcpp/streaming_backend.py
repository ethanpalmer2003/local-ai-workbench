"""Resident CPU C API service for true paced Nemotron streams."""

import os
import sys
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared.resident_backend import ResidentBackend
from scripts.launchers.shared.services import native


class CpuBackend(ResidentBackend):
    def __init__(self):
        super().__init__(cfg.PARAKEETCPP_STREAM_ASR)

    def command(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "scripts.launchers.asr.parakeetcpp.streaming_server",
            "--port",
            str(self.settings.port),
        ]

    def start(self):
        command = self.command()
        return native.start_server(
            command,
            [Path(sys.executable), cfg.PARAKEETCPP_STREAM_LIBRARY, self.model()],
            self.settings.port,
            "Parakeet CPU Nemotron stream",
            self.ready,
            lambda: native.matches(command),
            env={**os.environ, "PYTHONPATH": str(project_cfg.BASE_DIR), "PARAKEET_DEVICE": "cpu"},
            component_key="asr/parakeetcpp",
        )
