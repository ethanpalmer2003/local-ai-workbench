"""Shared external AudioCpp/Kokoro CPU startup and environment."""

import json
import os
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.config.models.gguf_metadata import inspect_metadata
from scripts.launchers import launcher_config as cfg


def available_voices(model_path: Path | None = None) -> list[dict[str, Any]]:
    metadata = inspect_metadata(
        model_path or cfg.KOKORO_TTS.audiocpp_model, full_array_keys=frozenset({"audiocpp.embedded_files.names"})
    )["metadata"]
    spec = json.loads(metadata.get("audiocpp.model_spec.json", "{}"))
    return [{"id": voice, "available": True} for voice in spec.get("ui", {}).get("builtin_voices", [])]


def language_profiles(model_path: Path | None = None) -> list[dict[str, Any]]:
    """Derive available language/voice pairs from this installed GGUF's model spec."""
    metadata = inspect_metadata(
        model_path or cfg.KOKORO_TTS.audiocpp_model, full_array_keys=frozenset({"audiocpp.embedded_files.names"})
    )["metadata"]
    spec = json.loads(metadata.get("audiocpp.model_spec.json", "{}"))
    files = metadata.get("audiocpp.embedded_files.names", [])
    if isinstance(files, dict):
        files = files.get("preview", [])
    voices = spec.get("ui", {}).get("builtin_voices", [])
    # Kokoro's voice-prefix convention is adapter data, not a second capability catalog.
    prefixes = {
        "en-us": "a",
        "en-gb": "b",
        "es": "e",
        "fr-fr": "f",
        "hi": "h",
        "it": "i",
        "ja": "j",
        "pt-br": "p",
        "zh": "z",
    }
    preferred = {"en-us": cfg.LANGUAGE_PRACTICE.tts_voice, "es": "ef_dora", "fr-fr": "ff_siwis", "ja": "jf_alpha"}
    rows = []
    for locale in spec.get("languages", []):
        prefix = prefixes.get(locale)
        candidates = [voice for voice in voices if prefix and voice.startswith(prefix)]
        if candidates:
            voice = preferred.get(locale, candidates[0])
            required = {"ja": ["g2p/ja.json", "unidic/dicrc"], "zh": ["g2p/zh.json"]}.get(locale, [])
            missing = [name for name in required if name not in files]
            if locale == "ja" and not cfg.KOKORO_TTS.mecab_library.is_file():
                missing.append("MeCab runtime DLL")
            rows.append(
                {
                    "code": locale.split("-")[0],
                    "locale": locale,
                    "voice": voice if voice in candidates else candidates[0],
                    "available": not missing,
                    "unavailable_reason": "Missing bundled resources: " + ", ".join(missing) if missing else "",
                }
            )
    return rows


def audio_command(
    port: int, config_path: Path | None = None, *, backend: str = "cpu", spec: dict[str, object] | None = None
) -> list[str]:
    """Start AudioCpp for one TTS model; Kokoro's package is the default when no spec is given."""
    selected = spec or {
        "id": cfg.KOKORO_TTS_PACKAGES[cfg.KOKORO_TTS.audiocpp_package],
        "family": "kokoro_tts",
        "path": str(cfg.KOKORO_TTS.audiocpp_model),
        "task": "tts",
        "mode": "streaming",
    }
    path = config_path or project_cfg.component("audiocpp").generated_dir / (
        f"kokoro-{port}.json" if backend == "cpu" else f"kokoro-{backend}-{port}.json"
    )
    config = {
        "host": "127.0.0.1",
        "port": port,
        "backend": backend,
        "threads": cfg.KOKORO_TTS.threads,
        "lazy_load": True,
        "models": [selected],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return [str(project_cfg.AUDIOCPP_SERVER_EXE), "--config", str(path), "--model", str(selected["id"])]


def audio_environment() -> dict[str, str]:
    return {
        **os.environ,
        "AUDIOCPP_ESPEAK_LIBRARY": str(cfg.KOKORO_TTS.espeak_dir / "libespeak-ng.dll"),
        "AUDIOCPP_ESPEAK_DATA": str(cfg.KOKORO_TTS.espeak_dir / "espeak-ng-data"),
        "AUDIOCPP_MECAB_LIBRARY": str(cfg.KOKORO_TTS.mecab_library),
    }
