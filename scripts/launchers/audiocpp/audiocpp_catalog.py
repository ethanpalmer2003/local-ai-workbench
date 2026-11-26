"""Configured audio models and locally usable clone references."""

import json
import wave
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

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
    spec = _configured_spec(model)
    return dict(spec.get("default_request_options", {})) if spec else {}


def _configured_spec(model: str) -> dict[str, Any] | None:
    """The server config's entry for one model, or None when it is not configured."""
    source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    specs = audio_cfg.read(source)["models"]
    return next((entry for entry in specs if entry["id"] == model), None)


def declares_voice_presets(model: str) -> bool:
    """Whether the model speaks its own named voices instead of a cloned reference."""
    spec = _configured_spec(model)
    return bool(spec) and _declares_voice_presets(spec)


def default_voice_for(model: str) -> str:
    """The voice a request for this model gets when it names none."""
    return model_default_voice(model, _configured_spec(model))


def configured_voices() -> list[dict[str, object]]:
    """One walk of the voice tree for every configured voice; each row names its built clips.

    `variants` is every reference built for that voice and `default_variant` is the one a clone
    actually uses, so a comparison can show the default rather than guess it.
    """
    found = _voice_refs()
    rows: list[dict[str, object]] = []
    for voice in cfg.AUDIOCPP_PROXY_CLONE_VOICES:
        reference = found.get(voice.lower())
        rows.append(
            {
                "id": voice,
                "available": reference is not None,
                "variants": voice_variants(voice) if reference is not None else [],
                "variant_seconds": voice_variant_seconds(voice) if reference is not None else {},
                "default_variant": reference.stem[len(voice) + 1 :] if reference is not None else "",
            }
        )
    return rows


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
    return {voice: _pick_reference(sorted(paths)) for voice, paths in matches.items()}


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
    voices = voice_data(selected, spec)
    accepted = accepted_request_options(selected)
    # - an option the model does not declare is dropped by the proxy, so the page must not offer it
    instruction_option = preset.instruction_option if preset else "instruction"
    if instruction_option and instruction_option not in accepted:
        instruction_option = None
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
        "voice": voices.get("default_voice") or (service.voice if voices.get("voice_mode") == "clone" else ""),
        "selected_model": selected,
        "model_identity": Path(spec["path"]).name if spec else selected,
        "instruction_option": instruction_option,
        "guidance_scale_option": "guidance_scale" if "guidance_scale" in accepted else None,
        "models": configured_models(),
        **voices,
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


# - Which built reference a clone uses when several exist: the 30 s cap first, because it keeps the
#   longest clean take inside Breeze's reference budget, then the 30 s floor build, then the rest
REFERENCE_VARIANTS = ("max30", "min30")


def _pick_reference(wavs: list[Path]) -> Path:
    """The reference a voice uses: a preferred variant when present, else the first by name."""
    for variant in REFERENCE_VARIANTS:
        for wav in wavs:
            if wav.stem.lower().endswith(f"_{variant}"):
                return wav
    return wavs[0]


def voice_variants(voice_name: str) -> list[str]:
    """Every built reference variant for one voice, by the suffix after `<voice>_`."""
    return sorted(voice_variant_seconds(voice_name))


def voice_variant_seconds(voice_name: str) -> dict[str, float]:
    """Each built reference variant and its length, which decides whether a small-context model can take it."""
    root = Path(cfg.AUDIOCPP_INPUT_DIR)
    folders = [d for d in (*root.glob("*"), *root.glob("*/*")) if d.is_dir() and d.name.lower() == voice_name]
    return {
        wav.stem[len(voice_name) + 1 :]: wav_seconds(wav)
        for folder in folders
        for wav in folder.rglob(f"{voice_name}_*.wav")
        if wav.stem.startswith(f"{voice_name}_")
    }


def resolve_voice_ref(voice_name: str, variant: str | None = None) -> tuple[str, str] | None:
    """
    - Find <voice>_*.wav inside a directory named for the voice, one or two levels below the input
      tree (e.g. <category>/<voice>/generated/), plus its matching .txt transcript
    - The search starts at the voice's own directory: the input tree also holds every model's
      assets, so walking all of it costs a directory scan per request
    - `variant` names one built reference (max30, min30, ...); omitted keeps the configured pick
    """
    root = Path(cfg.AUDIOCPP_INPUT_DIR)
    folders = [d for d in (*root.glob("*"), *root.glob("*/*")) if d.is_dir() and d.name.lower() == voice_name]
    wavs = sorted(f for folder in folders for f in folder.rglob(f"{voice_name}_*.wav"))
    if variant:
        wavs = [wav for wav in wavs if wav.stem.lower() == f"{voice_name}_{variant}".lower()]
    if not wavs:
        return None
    wav = _pick_reference(wavs)
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
                # - a reference-driven checkpoint clones; the light Ming checkpoint also speaks named voices,
                #   which `voice_data` reports as both, so the two capabilities are recorded separately
                "clone": spec["id"] != cfg.AudiocppModel.BREEZE_DESIGN.value and _accepts_reference(path),
                # - a checkpoint with a small context refuses a long reference; the launcher states its cap
                "reference_seconds_limit": cfg.AUDIOCPP_MODEL_REFERENCE_LIMITS.get(spec["id"]),
            }
        )
    return models


def wav_seconds(path: Path) -> float:
    """A WAV's length from its header, so a long reference costs no decode to reject."""
    try:
        with wave.open(str(path)) as handle:
            framerate = handle.getframerate()
            return handle.getnframes() / framerate if framerate else 0.0
    except (wave.Error, OSError, EOFError):
        return 0.0


def _accepts_reference(path: Path) -> bool:
    """Whether the packaged model spec takes a reference clip, which is the cloning path."""
    entries = _safe_spec(path).get("options", {}).get("request", []) if path.is_file() else []
    return any(entry.get("name") == "reference_text" for entry in entries)


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
    clone = next((row["clone"] for row in configured_models() if row["id"] == model), False)
    if spec and _declares_voice_presets(spec):
        path = Path(spec["path"])
        presets = builtin_voices(path) if path.is_file() else []
        if clone:
            # - the light Ming checkpoint takes a preset speaker or a cloned reference, so both lists apply
            #   and the page marks which names are references rather than packaged speakers
            references = configured_voices()
            return {
                "voice_mode": "both",
                "voices": presets + references,
                "clone_voices": [voice["id"] for voice in references],
                "default_voice": model_default_voice(model, spec),
            }
        return {"voice_mode": "builtin", "voices": presets, "default_voice": model_default_voice(model, spec)}
    if clone:
        return {
            "voice_mode": "clone",
            "voices": configured_voices(),
            "default_voice": cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value,
        }
    return {"voice_mode": "none", "voices": [], "default_voice": ""}


def _safe_spec(path: Path) -> dict[str, Any]:
    """The packaged spec, or empty when the file is absent or not a readable GGUF."""
    try:
        return packaged_spec(path)
    except (OSError, ValueError):
        return {}


def _voice_option(path: Path) -> dict[str, Any]:
    """The packaged voice_id option, empty when the model takes no preset voice."""
    entries = _safe_spec(path).get("options", {}).get("request", [])
    return next((entry for entry in entries if entry.get("name") == "voice_id"), {})


def _declares_voice_presets(spec: dict[str, Any]) -> bool:
    """Whether the model speaks its own named voices; a clone-only checkpoint declares none here."""
    return spec.get("family") in cfg.TTS_FAMILY_DEFAULT_VOICE


def model_default_voice(model: str, spec: dict[str, Any] | None) -> str:
    """The voice this model speaks when a request names none: its family pick, else its packaged default."""
    if not spec:
        return ""
    family = spec.get("family")
    if family in cfg.TTS_FAMILY_DEFAULT_VOICE:
        return cfg.TTS_FAMILY_DEFAULT_VOICE[family]
    path = Path(spec["path"])
    if not path.is_file():
        return ""
    option = _voice_option(path)
    return str(option.get("default") or next(iter(option.get("values") or []), ""))


def supports_clone(model: str) -> bool:
    return any(row["id"] == model and row["clone"] for row in configured_models())


class ComparisonCatalog(TypedDict):
    """What the comparison page loads: selectable voices, clone models and built reference clips."""

    voices: list[dict[str, object]]
    models: list[dict[str, object]]
    variants: list[str]


def comparison_catalog() -> ComparisonCatalog:
    """Voices, clone models and the built reference variants a comparison can choose between."""
    voices = configured_voices()
    variants = sorted(
        {variant for voice in voices if voice["available"] for variant in voice_variants(str(voice["id"]))}
    )
    return {"voices": voices, "models": configured_models(), "variants": variants}


def validate_comparison(payload: Payload) -> None:
    models = configured_models()
    if not any(model["id"] == payload.get("model") and model["installed"] and model["clone"] for model in models):
        raise ComparisonSelectionError(
            "Comparison requires an installed, configured clone-capable model; no fallback was used"
        )
    voice = str(payload.get("voice", ""))
    if voice not in cfg.AUDIOCPP_PROXY_CLONE_VOICES or resolve_voice_ref(voice) is None:
        raise ComparisonSelectionError(f"Comparison voice {voice!r} has no usable reference; no fallback was used")
