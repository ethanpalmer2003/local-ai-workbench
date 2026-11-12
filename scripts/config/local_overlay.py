"""Local overlay: every file this repo reads from outside git, reached through this one module."""

import os
from pathlib import Path
from typing import Any, cast

import yaml

from scripts.config import project_config as project_cfg


def input_dir() -> Path:
    """Root of the local overlay; AI_INPUT_DIR lets another checkout supply the same tree."""
    return Path(os.environ.get("AI_INPUT_DIR") or project_cfg.INPUT_DIR)


def voices_dir() -> Path:
    """Downloaded clip libraries; assets like model weights, not authored overlay config."""
    return Path(os.environ.get("AI_VOICES_DIR") or project_cfg.VOICES_DIR)


def kobold_dir() -> Path:
    return input_dir() / "kobold"


def prompts_dir() -> Path:
    return input_dir() / "prompts"


def voice_sources_path() -> Path:
    """Manifest of downloadable voice sources; absent means no voice pipeline entries."""
    return input_dir() / "voice_sources.yaml"


def model_overlay_path() -> Path:
    """Extra model catalog entries: character LoRAs and other personal weights."""
    return input_dir() / "models.overlay.yaml"


def _manifest(path: Path) -> dict[str, Any]:
    """One hand-authored overlay manifest; YAML so the file can carry comments."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def voice_ids() -> tuple[str, ...]:
    """Ids from the manifest, else the folders already present under the input tree.

    A superseded id sorts last, so the first voice a picker offers is a current one.
    """
    manifest = voice_sources_path()
    if manifest.is_file():
        payload = _manifest(manifest)
        voices = payload.get("voices") or {}
        if voices:
            superseded = superseded_voices()
            return tuple(sorted(voices, key=lambda name: (name in superseded, name)))
    folder = voices_dir()
    if folder.is_dir():
        return tuple(sorted(path.name for path in folder.iterdir() if path.is_dir()))
    return ()


def superseded_voices() -> dict[str, str]:
    """Voice ids replaced by another id: `superseded_by` keeps the old clips usable but secondary."""
    manifest = voice_sources_path()
    if not manifest.is_file():
        return {}
    payload = _manifest(manifest)
    pairs: dict[str, str] = {}
    for name, entry in (payload.get("voices") or {}).items():
        replacement = entry.get("superseded_by") if isinstance(entry, dict) else None
        if isinstance(replacement, str) and replacement and replacement != name:
            pairs[name] = replacement
    return pairs


def default_voice() -> str:
    """The manifest's chosen default, else the first discovered id, else empty."""
    manifest = voice_sources_path()
    if manifest.is_file():
        payload = _manifest(manifest)
        chosen = str(payload.get("default") or "")
        if chosen and (not payload.get("voices") or chosen in payload["voices"]):
            return chosen
    ids = voice_ids()
    return ids[0] if ids else ""


def voice_dir(voice_id: str) -> Path:
    return voices_dir() / voice_id


def character_cards() -> dict[str, Path]:
    """Saved character/scenario files; the caller decides what to do with them."""
    folder = kobold_dir()
    if not folder.is_dir():
        return {}
    return {path.stem: path for path in sorted(folder.glob("*")) if path.suffix in (".txt", ".json")}


def tone_prompt() -> str | None:
    """Voice/tone instruction text used by the TTS prompt path, when one is supplied."""
    for name in ("tone_tags.txt", "tone_instructions.txt"):
        path = prompts_dir() / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return None


def overrides_path() -> Path:
    """Optional overlay file that replaces code-owned defaults with personal ones."""
    return input_dir() / "defaults.yaml"


def overrides() -> dict[str, object]:
    path = overrides_path()
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def setting[T](key: str, fallback: T) -> T:
    """Dotted lookup in the overlay's defaults.yaml, e.g. setting("chat.tts.voice", "").

    A missing key, a wrong container type or a value of the wrong type keeps the
    repository default, so the overlay can never break a launcher.
    """
    node: object = overrides()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return fallback
        node = node[part]
    if isinstance(fallback, bool):
        return cast(T, node) if isinstance(node, bool) else fallback
    return cast(T, node) if isinstance(node, type(fallback)) else fallback
