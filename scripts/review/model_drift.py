"""Check that selected and native runtime models resolve to the model catalog."""

import json
from collections import Counter
from pathlib import Path

from scripts.config import models
from scripts.config.audiocpp import server as audiocpp_server
from scripts.launchers import launcher_config as cfg


def normalized(path: str | Path) -> str:
    return str(Path(path).resolve()).casefold()


def inspect() -> list[str]:
    issues: list[str] = []
    labels = [model.label for model in models.MODELS]
    duplicates = sorted(label for label, count in Counter(labels).items() if count > 1)
    issues.extend(f"Duplicate catalog ID: {label}" for label in duplicates)
    catalog = {model.label: model for model in models.MODELS}
    paths = {normalized(model.path): model.label for model in models.MODELS}

    selected = {
        "KOBOLD_CHAT.llm_model": cfg.KOBOLD_CHAT.llm_model,
        "KOBOLD_CHAT.tts_model": cfg.KOBOLD_CHAT.tts_model,
        "LANGUAGE_PRACTICE.llm_model": cfg.LANGUAGE_PRACTICE.llm_model,
        "LANGUAGE_PRACTICE.tts_model": cfg.LANGUAGE_PRACTICE.tts_model,
    }
    if cfg.DEFAULT_KOKORO_PACKAGE not in cfg.KOKORO_TTS_PACKAGES:
        issues.append(f"Unknown default Kokoro package: {cfg.DEFAULT_KOKORO_PACKAGE}")
    for owner, model_id in selected.items():
        if model_id not in catalog:
            issues.append(f"{owner} references unknown catalog ID: {model_id}")
    for package, model_id in cfg.KOKORO_TTS_PACKAGES.items():
        if model_id not in catalog:
            issues.append(f"KOKORO_TTS_PACKAGES[{package!r}] references unknown catalog ID: {model_id}")

    try:
        runtime = audiocpp_server.read()
    except (OSError, json.JSONDecodeError) as error:
        return [*issues, f"Cannot read AudioCpp server config: {error}"]

    runtime_models = runtime.get("models", [])
    if not isinstance(runtime_models, list):
        return [*issues, "AudioCpp server config 'models' must be a list"]
    runtime_ids = [
        item["id"]
        for item in runtime_models
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    duplicates = sorted(model_id for model_id, count in Counter(runtime_ids).items() if count > 1)
    issues.extend(f"Duplicate AudioCpp runtime ID: {model_id}" for model_id in duplicates)

    for item in runtime_models:
        if not isinstance(item, dict):
            issues.append("AudioCpp server config contains a non-object model entry")
            continue
        model_id, model_path = item.get("id"), item.get("path")
        if not isinstance(model_id, str) or not isinstance(model_path, str):
            issues.append("AudioCpp model entry must have string 'id' and 'path' fields")
            continue
        registered = catalog.get(model_id)
        if registered is not None:
            expected_path = normalized(registered.path)
            if normalized(model_path) != expected_path:
                issues.append(
                    f"AudioCpp model {model_id} path differs from catalog path {registered.path}"
                )
        elif normalized(model_path) not in paths:
            issues.append(f"AudioCpp model {model_id} has no matching catalog model/path")

    accepted = set(cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS)
    speech_ids = {
        item["id"]
        for item in runtime_models
        if isinstance(item, dict)
        and item.get("task") in {"tts", "clon"}
        and isinstance(item.get("id"), str)
    }
    missing = sorted(accepted - speech_ids)
    extra = sorted(speech_ids - accepted)
    issues.extend(f"AudioCpp proxy accepts an ID absent from server.json: {model_id}" for model_id in missing)
    issues.extend(f"AudioCpp server TTS ID is not accepted by the proxy: {model_id}" for model_id in extra)
    return issues


def main() -> int:
    issues = inspect()
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}")
        return 1
    print("[OK] Workflow model selections and AudioCpp runtime entries match the model catalog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
