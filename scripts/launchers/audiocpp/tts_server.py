"""External AudioCpp TTS server startup and environment for any installed speech model."""

import json
import os
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime import gpu_selection


def audio_command(
    port: int, spec: dict[str, Any], config_path: Path | None = None, *, backend: str = "cpu"
) -> list[str]:
    """Start AudioCpp for one TTS model; the caller owns which model that is."""
    path = config_path or project_cfg.component("audiocpp").generated_dir / (
        f"tts-{port}.json" if backend == "cpu" else f"tts-{backend}-{port}.json"
    )
    config = {
        "host": "127.0.0.1",
        "port": port,
        "backend": backend,
        "threads": cfg.AUDIOCPP_SPEECH.threads,
        "lazy_load": True,
        "models": [spec],
    }
    if backend != "cpu":
        # - the native server takes an ordinal, resolved from the tracked adapter name at launch
        config["device"] = gpu_selection.device_for_binary(project_cfg.AUDIOCPP_SERVER_EXE).index
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return [str(project_cfg.AUDIOCPP_SERVER_EXE), "--config", str(path), "--model", str(spec["id"])]


def audio_environment() -> dict[str, str]:
    """The process environment the server needs: its linked eSpeak NG and MeCab frontends."""
    return {
        **os.environ,
        "AUDIOCPP_ESPEAK_LIBRARY": str(cfg.AUDIOCPP_SPEECH.espeak_dir / "libespeak-ng.dll"),
        "AUDIOCPP_ESPEAK_DATA": str(cfg.AUDIOCPP_SPEECH.espeak_dir / "espeak-ng-data"),
        "AUDIOCPP_MECAB_LIBRARY": str(cfg.AUDIOCPP_SPEECH.mecab_library),
    }
