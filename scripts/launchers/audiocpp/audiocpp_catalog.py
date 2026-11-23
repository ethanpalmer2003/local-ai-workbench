"""Configured audio models and locally usable clone references."""

import json
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from scripts.config import models as model_cfg
from scripts.config.audiocpp import server as audio_cfg
from scripts.config.models.gguf_metadata import read_metadata
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import tts_text_processing

Payload = dict[str, object]
ModelSpec = dict[str, Any]
# - audio.cpp accepts these spellings even though the packaged spec names only the canonical one,
#   so a client key here is not a request the server would refuse
REQUEST_OPTION_ALIASES = {"instruction": "instruct"}


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
    """One walk of the voice tree for every configured voice; a walk per voice cost seconds."""
    found = _voice_refs()
    return [{"id": voice, "available": voice.lower() in found} for voice in cfg.AUDIOCPP_PROXY_CLONE_VOICES]


def _voice_refs() -> dict[str, Path]:
    """Voice name -> its first reference clip, for every `<voice>/` folder at any depth."""
    root = Path(cfg.AUDIOCPP_INPUT_DIR)
    if not root.is_dir():
        return {}
    matches: dict[str, list[Path]] = {}
    for wav in root.rglob("*.wav"):
        for folder in (part.lower() for part in wav.relative_to(root).parts[:-1]):
            if wav.name.startswith(f"{folder}_"):
                matches.setdefault(folder, []).append(wav)
    return {voice: sorted(paths)[0] for voice, paths in matches.items()}


def breeze_defaults() -> tuple[dict[str, object], str]:
    """Breeze's configured guidance and instruction defaults, and the last tone this process applied.

    The last tone is not a default: it is what the previous request inherited, so the page shows it as a
    note rather than filling it in, and a configured empty instruction stays empty.
    """
    tones = tts_text_processing.BREEZE_TONES
    inherited = tts_text_processing.tone_state.last if tones.tags_enabled else None
    return {"guidance_scale": tones.guidance_scale, "instruction": tones.default_instruction}, inherited or ""


def runtime_defaults(
    service: cfg.AudiocppStartupRequestServiceSettings, model: str | None = None, specs: list[ModelSpec] | None = None
) -> dict[str, object]:
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
    inherited_tone = ""
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
        proxy, inherited_tone = breeze_defaults()
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
        "inherited_tone": inherited_tone,
        # - the page's practice view starts on the language-practice voice; the test view starts on this
        #   proxy's own service model, so Breeze stays one route away
        "practice_model": cfg.LANGUAGE_PRACTICE.tts_model,
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
    - Find <voice>_*.wav inside a directory named for the voice, one or two levels below the input
      tree (e.g. <category>/<voice>/generated/), plus its matching .txt transcript
    - The search starts at the voice's own directory: the input tree also holds every model's
      assets, so walking all of it costs a directory scan per request
    """
    root = Path(cfg.AUDIOCPP_INPUT_DIR)
    folders = [d for d in (*root.glob("*"), *root.glob("*/*")) if d.is_dir() and d.name.lower() == voice_name]
    wavs = sorted(f for folder in folders for f in folder.rglob(f"{voice_name}_*.wav"))
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
                # - Builtin-voice families take preset ids, so they never need a clone reference.
                "clone": spec["id"] != cfg.AudiocppModel.BREEZE_DESIGN.value
                and spec.get("family") not in cfg.TTS_FAMILY_DEFAULT_VOICE,
            }
        )
    return models


def packaged_spec(path: Path) -> dict[str, Any]:
    """The AudioCpp model spec embedded in an installed GGUF."""
    return json.loads(read_metadata(path).get("audiocpp.model_spec.json", "{}"))


def request_option_names(model: str) -> frozenset[str]:
    """The request options the installed model declares; empty when its spec names none."""
    try:
        path = model_cfg.path(model)
    except KeyError:
        return frozenset()
    if not path.is_file():
        return frozenset()
    entries = packaged_spec(path).get("options", {}).get("request", [])
    return frozenset(entry["name"] for entry in entries if "name" in entry)


def accepted_request_options(model: str) -> frozenset[str]:
    """Declared options plus the spellings audio.cpp accepts for them; empty when the spec names none."""
    declared = request_option_names(model)
    return declared | {alias for alias, canonical in REQUEST_OPTION_ALIASES.items() if canonical in declared}


def builtin_voices(path: Path) -> list[dict[str, object]]:
    """Voice presets declared by the GGUF: the UI list, else a voice_id request enum."""
    spec = packaged_spec(path)
    voices = spec.get("ui", {}).get("builtin_voices", [])
    if not voices:
        voices = next(
            (
                entry.get("values", [])
                for entry in spec.get("options", {}).get("request", [])
                if entry.get("name") == "voice_id"
            ),
            [],
        )
    return [{"id": voice, "available": True} for voice in voices]


def voice_data(model: str, spec: dict[str, Any] | None) -> dict[str, object]:
    if spec and spec.get("family") in cfg.TTS_FAMILY_DEFAULT_VOICE:
        path = Path(spec["path"])
        voices = builtin_voices(path) if path.is_file() else []
        return {
            "voice_mode": "builtin",
            "voices": voices,
            "default_voice": cfg.TTS_FAMILY_DEFAULT_VOICE[spec["family"]],
        }
    clone = next((row["clone"] for row in configured_models() if row["id"] == model), False)
    if clone:
        return {
            "voice_mode": "clone",
            "voices": configured_voices(),
            "default_voice": cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value,
        }
    return {"voice_mode": "none", "voices": [], "default_voice": ""}


def supports_clone(model: str) -> bool:
    return any(row["id"] == model and row["clone"] for row in configured_models())


def comparison_catalog() -> dict[str, list[dict[str, object]]]:
    return {"voices": configured_voices(), "models": configured_models()}


def validate_comparison(payload: Payload) -> None:
    models = configured_models()
    if not any(model["id"] == payload.get("model") and model["installed"] and model["clone"] for model in models):
        raise ComparisonSelectionError(
            "Comparison requires an installed, configured clone-capable model; no fallback was used"
        )
    voice = str(payload.get("voice", ""))
    if voice not in cfg.AUDIOCPP_PROXY_CLONE_VOICES or resolve_voice_ref(voice) is None:
        raise ComparisonSelectionError(f"Comparison voice {voice!r} has no usable reference; no fallback was used")
