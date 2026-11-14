"""Resident file-transcription lifecycle from canonical ASR profiles."""

import json
import os
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import requests
from scripts.launchers.asr.shared.resident_profiles import build_server_command
from scripts.launchers.shared.services import native
from scripts.shared.wait import http_ready


class ResidentBackend:
    def __init__(self, settings: cfg.ResidentAsrStartupSettings):
        self.settings = settings

    def url(self) -> str:
        return f"http://127.0.0.1:{self.settings.port}"

    def ready(self) -> bool:
        return http_ready(self.url() + "/health")

    def command(self) -> list[str]:
        command = build_server_command(self.settings.profile, self.settings.port)
        if "{config}" in command:
            from scripts.launchers.asr.shared.resident_profiles import audio_config

            path = (
                project_cfg.component(ASR_FILE_PROFILES[self.settings.profile].component).generated_dir
                / f"{self.settings.profile}-{self.settings.port}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(audio_config(self.settings.profile)), encoding="utf-8")
            command = [part.replace("{config}", str(path)) for part in command]
        return command

    def model(self) -> Path:
        return model_cfg.path(ASR_FILE_PROFILES[self.settings.profile].models[0])

    def start(self):
        profile = ASR_FILE_PROFILES[self.settings.profile]
        command = self.command()
        return native.start_server(
            command,
            [Path(command[0]), self.model()],
            self.settings.port,
            self.settings.profile,
            self.ready,
            lambda: native.matches(command),
            env={**os.environ, **dict(profile.environment_overrides)},
            component_key=profile.component,
        )

    def transcribe(self, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
        request = requests.parse(body, content_type)
        if request.suppress_non_speech:
            raise ValueError("Non-speech token suppression is a Whisper-specific option")
        from scripts.launchers.shared.transport.multipart import audio_upload

        fields = {"response_format": "json"}
        if ASR_FILE_PROFILES[self.settings.profile].audio_family:
            fields["model"] = "benchmark-asr"
        # Parakeet v3 auto-detects; its server does not implement language forcing.
        if self.settings.profile != "parakeetcpp-v3":
            fields["language"] = request.language
        body, content_type = audio_upload(request.audio, fields)
        return requests.post(self.url() + "/v1/audio/transcriptions", body, content_type, headers)
