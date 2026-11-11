"""Canonical model catalog: data file, loader, and generated Python IDs."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from scripts.config import overlay_inputs as inputs
from scripts.config import project_config as project_cfg

from .types import ModelDownload

CATEGORIES = ("llms", "asr", "tts", "images", "embeddings")
CATALOG_PATH = project_cfg.CONFIG_DIR / "models" / "catalog.json"
IDS_PATH = project_cfg.CONFIG_DIR / "models" / "ids.py"
CATALOG_VERSION = 1
SHA256 = re.compile(r"^[a-f0-9]{64}$")


def filename_from_destination(group: str, destination: str) -> str:
    base = project_cfg.component(group).models_dir.relative_to(project_cfg.DATA_DIR)
    return Path(destination).relative_to(base).as_posix()


def _destination(group: str, label: str, raw: dict[str, Any], destinations: set[str]) -> tuple[str, str]:
    """Resolve the filename/destination pair and prove it stays inside the owner."""
    filename = raw.get("filename")
    destination = raw.get("destination")
    if destination is None:
        if not filename:
            raise ValueError(f"Model {label} needs filename or destination")
        destination = project_cfg.model_destination(group, str(filename))
    if filename is None:
        filename = filename_from_destination(group, str(destination))
    destination = str(destination)
    if Path(destination).is_absolute() or ".." in Path(destination).parts:
        raise ValueError(f"Model destination must be relative: {label}")
    if destination in destinations:
        raise ValueError(f"Duplicate model destination: {destination}")
    target = (project_cfg.DATA_DIR / destination).resolve()
    if not target.is_relative_to(project_cfg.component(group).models_dir.resolve()):
        raise ValueError(f"Model destination is outside its owner: {label}")
    return str(filename), destination


def _download_fields(raw: dict[str, Any], label: str) -> tuple[str | None, bool, str | None, list[Any], list[Any]]:
    url = raw.get("url")
    in_use = bool(raw.get("in_use", False))
    if in_use and not url:
        raise ValueError(f"Active model has no download URL: {label}")
    sha256 = raw.get("sha256")
    if sha256 is not None and not SHA256.match(str(sha256)):
        raise ValueError(f"Invalid SHA256 for {label}")
    roles = raw.get("roles") or []
    runtimes = raw.get("runtimes") or []
    if not isinstance(roles, list) or not isinstance(runtimes, list):
        raise ValueError(f"Model roles/runtimes must be lists: {label}")
    return (str(url) if url else None), in_use, (str(sha256) if sha256 else None), roles, runtimes


def _entry(raw: dict[str, Any], labels: set[str], destinations: set[str]) -> ModelDownload:
    """Validate one catalog entry and register its uniqueness keys."""
    category = str(raw.get("category", ""))
    group = str(raw.get("group", ""))
    label = str(raw.get("label", ""))
    if category not in CATEGORIES:
        raise ValueError(f"Unknown model category for {label}: {category}")
    if group not in project_cfg.COMPONENTS:
        raise ValueError(f"Unknown model owner for {label}: {group}")
    if not label.startswith(group + "/"):
        raise ValueError(f"Model label does not match its owner: {label}")
    if label in labels:
        raise ValueError(f"Duplicate model label: {label}")
    filename, destination = _destination(group, label, raw, destinations)
    url, in_use, sha256, roles, runtimes = _download_fields(raw, label)
    labels.add(label)
    destinations.add(destination)
    return ModelDownload(
        group,
        label,
        url,
        destination,
        in_use,
        str(raw.get("notes") or ""),
        sha256,
        tuple(str(item) for item in roles),
        tuple(str(item) for item in runtimes),
        str(raw["source_page"]) if raw.get("source_page") else None,
        filename,
        category,
    )


def _build(payload: dict[str, Any]) -> tuple[ModelDownload, ...]:
    if payload.get("version") != CATALOG_VERSION:
        raise ValueError(f"Unsupported model catalog version: {payload.get('version')}")
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raise ValueError("Model catalog 'models' must be a list")
    models: list[ModelDownload] = []
    labels: set[str] = set()
    destinations: set[str] = set()
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise ValueError("Model catalog entries must be objects")
        models.append(_entry(raw, labels, destinations))
    return tuple(models)


@lru_cache(maxsize=8)
def _load(path: str, overlay: bool) -> tuple[ModelDownload, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if overlay and Path(path) == CATALOG_PATH.resolve() and inputs.model_overlay_path().is_file():
        # - personal entries stay in the input overlay, never in the tracked catalog
        extra = json.loads(inputs.model_overlay_path().read_text(encoding="utf-8")).get("models") or []
        payload["models"] = [*payload.get("models", []), *extra]
    return _build(payload)


def load_catalog(path: Path | None = None, overlay: bool = True) -> tuple[ModelDownload, ...]:
    """MODELS includes the private overlay; the tracked ids.py is generated with overlay=False."""
    return _load(str((path or CATALOG_PATH).resolve()), overlay)


def clear_cache() -> None:
    _load.cache_clear()


MODELS = load_catalog()


def models_for(category: str) -> tuple[ModelDownload, ...]:
    return tuple(model for model in load_catalog() if model.category == category)


def get(label: str) -> ModelDownload:
    key = str(label)
    for model in load_catalog():
        if model.label == key:
            return model
    raise KeyError(f"Unknown model catalog ID: {key}")


def path(label: str) -> Path:
    return get(label).path


def filename(label: str) -> str:
    model = get(label)
    if model.filename is None:
        raise KeyError(f"No filename recorded for model: {label}")
    return model.filename


def destination(label: str) -> str:
    return get(label).destination


def label_for_path(value: Path) -> str | None:
    candidate = value.resolve()
    for model in load_catalog():
        target = model.path.resolve()
        if candidate == target:
            return model.label
        marker = "-00001-of-"
        if marker in target.name:
            prefix = target.name.split(marker, 1)[0]
            if candidate.parent == target.parent and candidate.name.startswith(prefix + "-"):
                return model.label
    return None


def entry_dict(model: ModelDownload) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "category": model.category,
        "group": model.group,
        "label": model.label,
        "filename": model.filename,
        "url": model.url,
        "in_use": model.in_use,
        "notes": model.notes,
        "sha256": model.sha256,
        "roles": list(model.roles),
        "runtimes": list(model.runtimes),
        "source_page": model.source_page,
    }
    return entry


def load_entries(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads((path or CATALOG_PATH).read_text(encoding="utf-8"))
    return list(payload.get("models") or [])


def overlay_path() -> Path:
    """The private overlay that carries personal entries; absent when no private checkout exists."""
    return inputs.model_overlay_path()


def entry_home(label: str) -> Path:
    """The file that lists this label: the tracked catalog first, otherwise the private overlay."""
    if any(str(entry.get("label")) == label for entry in load_entries()):
        return CATALOG_PATH
    return overlay_path()


def _save_entries(entries: list[dict[str, Any]], target: Path) -> None:
    if target == CATALOG_PATH:
        save_catalog(entries)
    else:
        save_catalog(entries, target)


def upsert_entry(entry: dict[str, Any], path: Path | None = None) -> Path:
    """Add or replace one entry in an explicit file, or in the file that already owns it."""
    target = path or entry_home(str(entry.get("label")))
    entries = [item for item in load_entries(target) if str(item.get("label")) != str(entry.get("label"))]
    _save_entries([*entries, entry], target)
    return target


def remove_entry(label: str) -> Path | None:
    """Drop one entry from its owning file; None when no file lists it."""
    home = entry_home(label)
    if not home.is_file():
        return None
    entries = load_entries(home)
    kept = [entry for entry in entries if str(entry.get("label")) != label]
    if len(kept) == len(entries):
        return None
    _save_entries(kept, home)
    return home


def validate_entries(entries: list[dict[str, Any]]) -> None:
    _build({"version": CATALOG_VERSION, "models": entries})


def save_catalog(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or CATALOG_PATH
    payload = {"version": CATALOG_VERSION, "models": entries}
    _build(payload)  # validate before writing
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    clear_cache()


def _constant_name(label: str) -> str:
    name = re.sub(r"[^0-9A-Za-z]+", "_", label).strip("_").upper()
    if not name or not name[0].isalpha():
        name = "MODEL_" + name
    return name


def render_ids(models: tuple[ModelDownload, ...] | None = None) -> str:
    models = MODELS if models is None else models
    used: set[str] = set()
    lines = []
    for model in sorted(models, key=lambda item: item.label):
        base = _constant_name(model.label)
        name = base
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        lines.append(f"    {name} = {json.dumps(model.label)}")
    body = "\n".join(lines) if lines else "    pass"
    return (
        '"""Generated by scripts.config.models.catalog; do not edit by hand."""\n\n'
        "from enum import StrEnum\n\n\n"
        "class ModelId(StrEnum):\n"
        f"{body}\n"
    )


def write_ids(models: tuple[ModelDownload, ...] | None = None, path: Path | None = None) -> None:
    # - ids.py is tracked, so it must never carry private overlay entries
    models = models if models is not None else load_catalog(overlay=False)

    target = path or IDS_PATH
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(render_ids(models), encoding="utf-8")
    os.replace(temporary, target)


def ids_match(models: tuple[ModelDownload, ...] | None = None, path: Path | None = None) -> bool:
    # - ids.py reflects the tracked catalog; overlay entries are deliberately absent
    target = path or IDS_PATH
    models = models if models is not None else load_catalog(overlay=False)
    return target.is_file() and target.read_text(encoding="utf-8") == render_ids(models)
