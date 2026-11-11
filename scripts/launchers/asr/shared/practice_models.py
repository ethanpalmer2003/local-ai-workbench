"""Practice model catalog and native TTS configuration; paths remain catalog-owned."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from scripts.config import models
from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_config
from scripts.config.models import model_languages
from scripts.config.shared import speech_delivery
from scripts.launchers import launcher_config as cfg

active_tts_id: str | None = None
DEFAULT_PRACTICE_LANGUAGE = "en"


def tts_id() -> str:
    return active_tts_id or cfg.LANGUAGE_PRACTICE.tts_model


def _native_tts_specs() -> list[dict[str, Any]]:
    specs = audio_config.read()["models"]
    tts_families = {spec["family"] for spec in specs if spec.get("task") == "tts"}
    return [
        spec
        for spec in specs
        if spec.get("task") == "tts"
        or (
            spec.get("task") == "clon"
            and spec.get("family", "").endswith("_tts")
            and spec["family"] not in tts_families
        )
    ]


def _catalog_model(native_spec: dict[str, Any]):
    exact = next(
        (model for model in models.MODELS if model.group == "audiocpp" and model.label == native_spec["id"]), None
    )
    if exact:
        return exact
    configured_path = Path(native_spec["path"])
    return next(
        (model for model in models.MODELS if model.group == "audiocpp" and model.path.name == configured_path.name),
        None,
    )


def tts_models() -> list[dict[str, Any]]:
    native_specs = _native_tts_specs()
    language_catalog = model_languages.read_catalog()["models"]
    rows: list[dict[str, Any]] = [
        {"id": key, "label": label, "family": "kokoro_tts"}
        for key, label in (
            (cfg.KOKORO_TTS_PACKAGES["multilingual"], "Kokoro: multilingual bundle"),
            (cfg.KOKORO_TTS_PACKAGES["small"], "Kokoro: compact bundle"),
        )
    ]
    labels = {
        "breeze_tts": "Breeze TTS 2: voice design",
        "ming3_tts": "Ming 3.0 TTS 0.5B",
        "fish_drama3": "Drama 3: heavy/offloaded",
        "supertonic": "Supertonic 3: 31 languages, preset voices",
    }
    for spec in native_specs:
        model = _catalog_model(spec)
        if model is None:
            continue
        rows.append(
            {
                "id": model.label,
                "label": labels.get(spec["family"], model.label),
                "family": spec["family"],
                "native_id": spec["id"],
            }
        )
    for row in rows:
        row["available"] = models.path(row["id"]).is_file()
        row["reason"] = "" if row["available"] else "Model file is not installed"
        if row["family"] == "kokoro_tts":
            spec = {"id": row["id"], "family": "kokoro_tts", "path": str(models.path(row["id"]))}
        else:
            spec = next((item for item in native_specs if item["id"] == row.get("native_id")), None)
        language_entry = next((entry for entry in language_catalog if row["id"] in entry["model_ids"]), None)
        row["default_language"] = (
            language_entry.get("practice_default_language", DEFAULT_PRACTICE_LANGUAGE)
            if language_entry
            else DEFAULT_PRACTICE_LANGUAGE
        )
        from scripts.launchers.audiocpp import audiocpp_catalog

        row.update(audiocpp_catalog.voice_data(row["id"], spec))
        if row.get("family") == "ming3_tts":
            from scripts.launchers.audiocpp.audiocpp_catalog import resolve_voice_ref

            if not resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value):
                row.update(available=False, reason="Prepare a reference voice for Ming cloning first")
    return rows


def tts_spec(key: str | None = None) -> dict[str, Any]:
    key = key or tts_id()
    if key in cfg.KOKORO_TTS_PACKAGES.values():
        return {"id": key, "family": "kokoro_tts", "path": str(models.path(key)), "task": "tts", "mode": "streaming"}
    for spec in _native_tts_specs():
        model = _catalog_model(spec)
        if model is not None and model.label == key:
            value = dict(spec)
            value["path"] = str(models.path(key))
            return value
    raise KeyError(f"Unknown AudioCpp TTS model: {key}")


def language_profiles():
    spec = tts_spec()
    if spec["family"] == "kokoro_tts":
        from scripts.launchers.audiocpp.kokoro import language_profiles as profiles

        return profiles(models.path(tts_id()))
    from scripts.config.models import model_languages

    entry = next(entry for entry in model_languages.read_catalog()["models"] if tts_id() in entry["model_ids"])
    voice = cfg.TTS_FAMILY_DEFAULT_VOICE.get(spec["family"], cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
    return [
        {"code": code, "locale": code, "voice": voice, "available": True, "unavailable_reason": ""}
        for code in entry["languages"] or []
    ]


def speech_body(payload: dict[str, object]) -> dict[str, object]:
    spec = tts_spec()
    plan = delivery_plan()
    payload["model"] = spec["id"]
    payload.setdefault("stream", plan["mode"] == "streaming")
    if payload["stream"] and "streaming" not in plan["supported"]:
        raise ValueError("Streaming is not supported by this TTS model")
    payload["response_format"] = "pcm" if payload["stream"] else "wav"
    if payload["stream"]:
        payload.setdefault("stream_format", "audio")
    else:
        payload.pop("stream_format", None)
    if spec["family"] == "kokoro_tts":
        from scripts.launchers.shared.media.text_processing import clean_speech_payload

        clean_speech_payload(payload, language=cfg.KOKORO_TTS.language)
        payload.setdefault("voice", cfg.KOKORO_TTS.voice)
        options = payload.setdefault("options", {})
        if not isinstance(options, dict):
            raise ValueError("Speech options must be an object")
        options.setdefault("language", cfg.KOKORO_TTS.language)
        return payload
    from scripts.launchers.audiocpp import audiocpp_catalog
    from scripts.launchers.audiocpp.audiocpp_proxy import _transform

    if spec["family"] == "supertonic":
        # - Preset voices live in request options; the language comes from the text, so no locale field.
        payload.pop("voice", None)
        options = payload.setdefault("options", {})
        if not isinstance(options, dict):
            raise ValueError("Speech options must be an object")
        options.setdefault("voice_id", cfg.SUPERTONIC_TTS.voice)
    elif audiocpp_catalog.supports_clone(spec["id"]):
        payload.setdefault("voice", cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
    else:
        payload.pop("voice", None)
    value = _transform(payload)
    if value is None:
        raise ValueError("Speech input is empty after text cleanup")
    return value


def delivery_plan():
    from scripts.launchers.audiocpp import audiocpp_catalog

    spec = tts_spec()
    service = replace(cfg.AUDIOCPP_SERVICE, model=spec["id"])
    preset = (
        cfg.AUDIOCPP_PROXY_MODEL_PRESETS.get(cfg.AudiocppModel(spec["id"]))
        if spec["id"] in cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS
        else None
    )
    streaming = spec.get("mode") == "streaming" and (preset is None or preset.streaming_supported)
    result = speech_delivery.resolve("tts", tts_id(), speech_delivery.tts_supported(streaming))
    result.update(audiocpp_catalog.streaming_defaults(service, spec["id"]))
    return result


def tts_command(port: int) -> list[str]:
    config = {
        "host": "127.0.0.1",
        "port": port,
        "backend": "vulkan",
        "device": 0,
        "threads": cfg.KOKORO_TTS.threads,
        "lazy_load": True,
        "models": [tts_spec()],
    }
    path = project_cfg.component("audiocpp").generated_dir / f"practice-tts-{port}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return [str(project_cfg.AUDIOCPP_SERVER_EXE), "--config", str(path), "--port", str(port)]
