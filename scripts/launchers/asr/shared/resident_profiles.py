"""ASR resident command catalog shared by launchers and benchmark consumers."""

import re
from pathlib import Path
from typing import Any

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.whispercpp.server import server_command


def build_server_command(engine: str, port: int) -> list[str]:
    profile = ASR_FILE_PROFILES[engine]
    if profile.server_arguments is None:
        raise ValueError(f"No configured server command for {engine}")
    values = {"port": str(port), "model": str(model_cfg.path(profile.models[0])), "config": "{config}"}
    return [
        str(profile.server_executable or profile.executable),
        *(part.format_map(values) for part in profile.server_arguments),
    ]


def audio_config(engine: str) -> dict[str, Any]:
    """ASR-only generated config; never mutate the user's TTS server selection."""
    profile = ASR_FILE_PROFILES[engine]
    if not profile.audio_family:
        raise ValueError(f"Not an AudioCpp ASR profile: {engine}")
    model: dict[str, Any] = {
        "id": "benchmark-asr",
        "family": profile.audio_family,
        "path": str(model_cfg.path(profile.models[0])),
        "task": "asr",
        "mode": "offline",
    }
    if profile.session_options:
        model["session_options"] = dict(profile.session_options)
    if profile.request_options:
        model["default_request_options"] = dict(profile.request_options)
    return {
        "host": "127.0.0.1",
        "backend": "hip" if engine.endswith("rocm") else "vulkan",
        "device": 0,
        "lazy_load": True,
        "models": [model],
    }


def clean_transcript(engine: str, text: str) -> str:
    if engine == "audiocpp-ming-audio-tiny":
        text = re.sub(r"^(?:[a-z]{2,3}(?:-[A-Za-z]{2})?|English|Chinese|French|Spanish)\t", "", text.strip())
    return text.strip()


def whisper_model() -> Path:
    return Path(str(cfg.KOBOLDCPP_KCPPS_ARGS["whispermodel"]))


def whisper_frameworks() -> dict[str, Path]:
    root = project_cfg.component("asr/whispercpp").framework_dir
    return {"external": root / "vulkan", "latest-vulkan": root / "vulkan-build", "vulkan-fa": root / "vulkan-build"}


def whisper_command(engine: str, port: int) -> list[str]:
    model = whisper_model()
    if engine == "internal":
        return [
            str(cfg.KOBOLDCPP_SERVICE.exe),
            "--nomodel",
            "--usevulkan",
            "0",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--whispermodel",
            str(model),
        ]
    return server_command(
        whisper_frameworks()[engine] / "whisper-server.exe", model, port, 4, 0, engine == "vulkan-fa", "en"
    )


def profiles(port: int) -> dict[str, tuple[list[str], Path]]:
    result = {
        name: (build_server_command(name, port), model_cfg.path(ASR_FILE_PROFILES[name].models[0]))
        for name in ASR_FILE_PROFILES
        if ASR_FILE_PROFILES[name].server_arguments is not None
    }
    model = model_cfg.path("asr/parakeetcpp/parakeet-tdt-ctc-110m-q8_0")
    for backend in ("cpu", "vulkan"):
        exe = project_cfg.component("asr/parakeetcpp").framework_dir / backend / "parakeet-server.exe"
        result["parakeetcpp-" + backend] = (
            [str(exe), "--model", str(model), "--port", str(port), "--threads", "4"],
            model,
        )
    for key, engine in (("whispercpp-vulkan-fa", "vulkan-fa"), ("koboldcpp-whisper", "internal")):
        result[key] = (whisper_command(engine, port), whisper_model())
    from scripts.launchers.asr.llamacpp import qwen3_asr

    # - Gemma audio measured 2.53 s against Qwen's 0.19 s and has its own capability row, so it is
    #   not re-measured here
    for key, backend, settings in (("llamacpp-qwen-1.7b", qwen3_asr, cfg.QWEN3_ASR),):
        command = backend.command()
        command[command.index("--port") + 1] = str(port)
        result[key] = (command, settings.model)
    granite = list(result["llamacpp-qwen-1.7b"][0])
    granite[granite.index("-m") + 1] = str(model_cfg.path("asr/llamacpp/granite-speech-5.0-2b-q8_0"))
    granite[granite.index("--mmproj") + 1] = str(model_cfg.path("asr/llamacpp/granite-speech-5.0-2b-mmproj-f16"))
    granite[granite.index("--alias") + 1] = "granite-asr"
    result["llamacpp-granite-5-2b"] = (granite, model_cfg.path("asr/llamacpp/granite-speech-5.0-2b-q8_0"))
    return result
