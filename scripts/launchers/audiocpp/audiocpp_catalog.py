"""Configured audio models and locally usable clone references."""

import json
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from scripts.config.audiocpp import server as audio_cfg
from scripts.config.models.gguf_metadata import read_metadata
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import tts_text_processing

Payload = dict[str, object]


class ComparisonSelectionError(ValueError):
    """A batch selection cannot be honored without substituting another model or voice."""


@lru_cache(maxsize=16)
def _packaged_defaults(path: Path, modified_ns: int, size: int) -> dict[str, object]:
    spec = json.loads(read_metadata(path).get("audiocpp.model_spec.json", "{}"))
    return {
        group: {entry["name"]: entry["default"] for entry in entries if "default" in entry}
        for group, entries in spec.get("options", {}).items()
    }


def streaming_defaults(
    service: cfg.AudiocppStartupRequestServiceSettings, model: str | None = None
) -> dict[str, object]:
    selected = model or service.model
    streaming = asdict(service.streaming)
    server = server_request_defaults(selected)
    preset = (
        cfg.AUDIOCPP_PROXY_MODEL_PRESETS.get(cfg.AudiocppModel(selected))
        if selected in cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS
        else None
    )
    for key in ("stream_frames_per_event", "stream_lookahead_margin", "stream_chunk_policy"):
        if streaming[key] is None:
            streaming[key] = server.get(key)
    if selected in cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS:
        if preset and preset.pcm_sample_rate is not None:
            streaming["pcm_sample_rate"] = preset.pcm_sample_rate
        if preset and preset.playback_buffer_ms is not None:
            streaming["playback_buffer_ms"] = preset.playback_buffer_ms
    return streaming


def streaming_default_sources(
    service: cfg.AudiocppStartupRequestServiceSettings, model: str | None = None
) -> dict[str, str]:
    selected = model or service.model
    server = server_request_defaults(selected)
    sources: dict[str, str] = {}
    for key in ("stream_frames_per_event", "stream_lookahead_margin", "stream_chunk_policy"):
        if getattr(service.streaming, key) is not None:
            sources[key] = "Launcher"
        elif key in server:
            sources[key] = "Server config"
    return sources


def server_request_defaults(model: str) -> dict[str, object]:
    source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    specs = audio_cfg.read(source)["models"]
    spec = next((entry for entry in specs if entry["id"] == model), None)
    return dict(spec.get("default_request_options", {})) if spec else {}


def configured_voices() -> list[dict[str, object]]:
    return [
        {"id": voice, "available": resolve_voice_ref(voice) is not None}
        for voice in cfg.AUDIOCPP_PROXY_CLONE_VOICES
    ]


def runtime_defaults(service: cfg.AudiocppStartupRequestServiceSettings, model: str | None = None, specs: list[dict[str, Any]] | None = None) -> dict[str, object]:
    selected = model or service.model
    source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    selected_specs: list[dict[str, Any]] = audio_cfg.read(source)["models"] if specs is None else specs
    spec = next((entry for entry in selected_specs if entry["id"] == selected), None)
    packaged: dict[str, object] = {}
    if spec:
        path = Path(spec["path"])
        if not path.is_absolute():
            path = source.parent / path
        if path.is_file() and path.suffix.lower() == ".gguf":
            stat = path.stat()
            packaged = _packaged_defaults(path, stat.st_mtime_ns, stat.st_size)
    proxy: dict[str, object] = {}
    streaming = streaming_defaults(service, selected)
    playback_buffer_source = "Launcher"
    preset = (
        cfg.AUDIOCPP_PROXY_MODEL_PRESETS.get(cfg.AudiocppModel(selected))
        if selected in cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS
        else None
    )
    if preset and preset.playback_buffer_ms is not None:
        playback_buffer_source = "Model preset"
    if selected in cfg.BREEZE_MODELS:
        tones = tts_text_processing.BREEZE_TONES
        inherited = tts_text_processing.tone_state.last if tones.tags_enabled else None
        proxy = {
            "guidance_scale": tones.guidance_scale,
            "instruction": inherited or tones.default_instruction,
        }
    return {
        "streaming_enabled": (
            (selected == service.model and service.streaming_enabled) or bool(spec and spec.get("mode") == "streaming")
        )
        and (preset.streaming_supported if preset else True),
        "streaming_supported": preset.streaming_supported if preset else True,
        "streaming": streaming,
        "streaming_sources": streaming_default_sources(service, selected),
        "playback_buffer_source": playback_buffer_source,
        "playback_note": preset.playback_note if preset else "",
        "practice_url": f"http://127.0.0.1:{cfg.LLAMACPP_PRACTICE.port}/practice",
        "model": service.model,
        "voice": service.voice,
        "selected_model": selected,
        "model_identity": Path(spec["path"]).name if spec else selected,
        "instruction_option": preset.instruction_option if preset else "instruction",
        "models": configured_models(),
        **voice_data(selected, spec),
        "proxy_defaults": proxy,
        "model_preset_defaults": preset.request_options if preset else {},
        "packaged_defaults": packaged,
        "server_session_options": spec.get("session_options", {}) if spec else {},
        "server_request_defaults": spec.get("default_request_options", {}) if spec else {},
        "packaged_defaults_source": "Installed GGUF model metadata; runtime overrides may differ",
        "tone_settings": asdict(tts_text_processing.BREEZE_TONES),
        "text_cleanup": asdict(cfg.SHARED_TTS_TEXT_CLEANUP),
    }


def resolve_voice_ref(voice_name: str) -> tuple[str, str] | None:
    """
    - Find <voice>_*.wav anywhere inside a <voice>/ directory (any category,
      any depth - e.g. generated/ artifacts)
    - Plus its matching .txt transcript
    """
    root = Path(cfg.AUDIOCPP_INPUT_DIR)
    wavs = sorted(
        f
        for f in root.rglob(f"{voice_name}_*.wav")
        if voice_name in (part.lower() for part in f.relative_to(root).parts[:-1])
    )
    if not wavs:
        return None
    wav = wavs[0]
    txt = wav.with_suffix(".txt")
    reference_text = txt.read_text(encoding="utf-8").strip() if txt.is_file() else ""
    return str(wav), reference_text


def configured_models() -> list[dict[str, object]]:
    source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    specs = audio_cfg.read(source)["models"]
    models = []
    for spec in specs:
        if spec["id"] not in cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS:
            continue
        path = Path(spec["path"])
        if not path.is_absolute():
            path = source.parent / path
        models.append(
            {
                "id": spec["id"],
                "installed": path.is_file(),
                "clone": spec["id"] != cfg.AudiocppModel.BREEZE_DESIGN.value,
            }
        )
    return models


def voice_data(model: str, spec: dict[str, Any] | None) -> dict[str, object]:
    if spec and spec.get('family') == 'kokoro_tts':
        from scripts.launchers.audiocpp.kokoro import available_voices
        path = Path(spec['path'])
        voices = available_voices(path) if path.is_file() else []
        return {'voice_mode': 'builtin', 'voices': voices, 'default_voice': cfg.KOKORO_TTS.voice}
    clone = next((row['clone'] for row in configured_models() if row['id'] == model), False)
    if clone:
        return {'voice_mode': 'clone', 'voices': configured_voices(),
                'default_voice': cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value}
    return {'voice_mode': 'none', 'voices': [], 'default_voice': ''}


def supports_clone(model: str) -> bool:
    return any(row['id'] == model and row['clone'] for row in configured_models())


def comparison_catalog() -> dict[str, list[dict[str, object]]]:
    return {
        "voices": configured_voices(),
        "models": configured_models(),
    }


def validate_comparison(payload: Payload) -> None:
    models = configured_models()
    if not any(model["id"] == payload.get("model") and model["installed"] and model["clone"] for model in models):
        raise ComparisonSelectionError(
            "Comparison requires an installed, configured clone-capable model; no fallback was used"
        )
    voice = str(payload.get("voice", ""))
    if voice not in cfg.AUDIOCPP_PROXY_CLONE_VOICES or resolve_voice_ref(voice) is None:
        raise ComparisonSelectionError(f"Comparison voice {voice!r} has no usable reference; no fallback was used")
