"""Practice language intersection: exact selected ASR checkpoint and installed Kokoro spec."""

from typing import Any

from scripts.config import models
from scripts.config.models import model_languages
from scripts.launchers.asr import selector
from scripts.launchers.asr.shared import practice_models


def capabilities(engine) -> dict[str, Any]:
    catalog = model_languages.read_catalog()
    names = catalog["language_names"]
    try:
        path = selector.model(engine).resolve()
    except KeyError:
        path = None
    ids = {model.label for model in models.MODELS if model.path.resolve() == path}
    entries = [entry for entry in catalog["models"] if ids & set(entry["model_ids"]) and "asr" in entry["tasks"]]
    entry = entries[0] if entries else None
    supported = entry["languages"] if entry else None
    ready = set(supported or [])
    tiers = entry.get("coverage_tiers", {}) if entry else {}
    if tiers:
        ready = {
            locale.split("-")[0] for tier in ("transcription_ready", "broad_coverage") for locale in tiers.get(tier, [])
        }
        if "nb" in ready:
            ready.add("no")
    profiles = practice_models.language_profiles()
    selected_tts = next(row for row in practice_models.tts_models() if row["id"] == practice_models.tts_id())
    common = []
    for profile in profiles:
        if profile["code"] in ready or supported is None:
            label = names.get(profile["code"], profile["code"]).title()
            if profile["locale"] in ("en-us", "en-gb"):
                label += " (UK)" if profile["locale"] == "en-gb" else " (US)"
            common.append(
                {**profile, "label": label, "asr_language": profile["code"] if supported is not None else "auto"}
            )

    def describe(codes):
        return [{"code": code, "name": names.get(code, code).title()} for code in codes or []]

    return {
        "asr": {
            "model": entry["name"] if entry else path.name if path else engine.value,
            "languages": describe(supported),
            "coverage_known": supported is not None,
            "ready_languages": sorted(ready),
            "coverage_tiers": tiers,
            "notes": entry["notes"] if entry else "Complete coverage not verified.",
        },
        "tts": {
            "model": selected_tts["label"],
            "languages": describe(sorted({row["code"] for row in profiles})),
            "profiles": profiles,
            "default_language": selected_tts["default_language"],
            "notes": "Voices/languages declared by installed model. Pronunciation quality is not validated by this list.",
        },
        "common": common,
    }
