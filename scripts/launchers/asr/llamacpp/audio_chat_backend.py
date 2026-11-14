"""Configured llama.cpp audio-chat ASR; reuse Gemma transport and native lifecycle."""

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.llamacpp import gemma_audio
from scripts.launchers.shared.services import native
from scripts.shared.wait import http_ready


class AudioChatBackend:
    def __init__(self, settings: cfg.GemmaAudioAsrStartupRequestSettings):
        self.settings = settings

    def url(self):
        return f"http://127.0.0.1:{self.settings.port}"

    def ready(self):
        return http_ready(self.url() + "/health", strict=True)

    def command(self):
        command = gemma_audio.command()
        for flag, value in (
            ("-m", self.settings.model),
            ("--mmproj", self.settings.mmproj),
            ("--port", self.settings.port),
            ("--alias", "practice-audio-asr"),
        ):
            command[command.index(flag) + 1] = str(value)
        return command

    def start(self):
        command = self.command()
        return native.start_server(
            command,
            (self.settings.exe, self.settings.model, self.settings.mmproj),
            self.settings.port,
            "Audio chat ASR",
            self.ready,
            lambda: native.matches(command),
            component_key="asr/llamacpp",
        )

    def transcribe(self, body, content_type, headers=None):
        return gemma_audio.transcribe(body, content_type, headers, server_url=self.url())
