"""Select the external language-practice transcription backend."""

import subprocess
from pathlib import Path
from typing import Any, Protocol

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.koboldcpp import gemma_audio as gemma_kobold
from scripts.launchers.asr.llamacpp import gemma_audio
from scripts.launchers.asr.llamacpp import qwen3_asr as qwen_asr
from scripts.launchers.asr.llamacpp.audio_chat_backend import AudioChatBackend
from scripts.launchers.asr.parakeetcpp.streaming_backend import CpuBackend
from scripts.launchers.asr.shared.resident_backend import ResidentBackend
from scripts.launchers.asr.whispercpp import server as whisper
from scripts.launchers.audiocpp import asr as audio_asr
from scripts.launchers.audiocpp import asr_qwen3


class TranscriptionBackend(Protocol):
    def url(self) -> str: ...
    def ready(self) -> bool: ...
    def command(self) -> list[str]: ...
    def start(self) -> subprocess.Popen[Any] | None: ...
    def transcribe(
        self, body: bytes, content_type: str, headers: dict[str, str] | None = None
    ) -> tuple[bytes, str]: ...


def external(engine: cfg.AsrStartupEngine | None) -> bool:
    """Whether a separate process transcribes; None means the stack has none, and embedded is Kobold's own."""
    return engine is not None and engine != cfg.AsrStartupEngine.EMBEDDED


def backend(engine: cfg.AsrStartupEngine | None = None) -> TranscriptionBackend:
    backends: dict[cfg.AsrStartupEngine, TranscriptionBackend] = {
        cfg.AsrStartupEngine.COHERE: ResidentBackend(cfg.COHERE_ASR),
        cfg.AsrStartupEngine.GRANITE: AudioChatBackend(cfg.GRANITE_AUDIO_ASR),
        cfg.AsrStartupEngine.AUDIOCPP: audio_asr,
        cfg.AsrStartupEngine.NEMO: ResidentBackend(cfg.NEMO_SPEECHCPP_ASR),
        cfg.AsrStartupEngine.PARAKEET_STREAM: CpuBackend(),
        cfg.AsrStartupEngine.SPEECHCPP: ResidentBackend(cfg.SPEECHCPP_ASR),
        cfg.AsrStartupEngine.PARAKEET_V3: ResidentBackend(cfg.PARAKEETCPP_V3_ASR),
        cfg.AsrStartupEngine.WHISPER_VULKAN: whisper,
        cfg.AsrStartupEngine.QWEN3_ASR: qwen_asr,
        cfg.AsrStartupEngine.QWEN3_AUDIOCPP: asr_qwen3,
        cfg.AsrStartupEngine.GEMMA_AUDIO: gemma_audio,
        cfg.AsrStartupEngine.GEMMA_KOBOLD: gemma_kobold,
    }
    return backends[engine or cfg.ASR_SERVICE.engine]


def model(engine: cfg.AsrStartupEngine | None = None) -> Path:
    return {
        cfg.AsrStartupEngine.COHERE: ResidentBackend(cfg.COHERE_ASR).model(),
        cfg.AsrStartupEngine.GRANITE: cfg.GRANITE_AUDIO_ASR.model,
        cfg.AsrStartupEngine.NEMO: ResidentBackend(cfg.NEMO_SPEECHCPP_ASR).model(),
        cfg.AsrStartupEngine.PARAKEET_STREAM: CpuBackend().model(),
        cfg.AsrStartupEngine.SPEECHCPP: ResidentBackend(cfg.SPEECHCPP_ASR).model(),
        cfg.AsrStartupEngine.PARAKEET_V3: ResidentBackend(cfg.PARAKEETCPP_V3_ASR).model(),
        cfg.AsrStartupEngine.AUDIOCPP: Path(audio_asr.speech_config(cfg.AUDIOCPP_VAD.server_port)["models"][0]["path"]),
        cfg.AsrStartupEngine.WHISPER_VULKAN: cfg.WHISPERCPP_ASR.model,
        cfg.AsrStartupEngine.QWEN3_ASR: cfg.QWEN3_ASR.model,
        cfg.AsrStartupEngine.QWEN3_AUDIOCPP: Path(
            asr_qwen3.speech_config(cfg.AUDIOCPP_VAD.server_port)["models"][0]["path"]
        ),
        cfg.AsrStartupEngine.GEMMA_AUDIO: cfg.GEMMA_AUDIO_ASR.model,
        cfg.AsrStartupEngine.GEMMA_KOBOLD: cfg.GEMMA_AUDIO_ASR.model,
    }[engine or cfg.ASR_SERVICE.engine]
