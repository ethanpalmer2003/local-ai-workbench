"""Local input overlay: personal voice references, characters and prompts live outside the repo."""

import json
import os
from pathlib import Path
from typing import cast

from scripts.config import project_config as project_cfg


def input_dir() -> Path:
    """Root of the local overlay; AI_INPUT_DIR lets a private checkout supply the same tree."""
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
    return input_dir() / "voice_sources.json"


def model_overlay_path() -> Path:
    """Extra model catalog entries: character LoRAs and other personal weights."""
    return input_dir() / "models.private.json"


def voice_ids() -> tuple[str, ...]:
    """Ids from the manifest, else the folders already present under the input tree."""
    manifest = voice_sources_path()
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        voices = payload.get("voices") or {}
        if voices:
            return tuple(sorted(voices))
    folder = voices_dir()
    if folder.is_dir():
        return tuple(sorted(path.name for path in folder.iterdir() if path.is_dir()))
    return ()


def default_voice() -> str:
    """The manifest's chosen default, else the first discovered id, else empty."""
    manifest = voice_sources_path()
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
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
    return input_dir() / "defaults.json"


def overrides() -> dict[str, object]:
    path = overrides_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(_without_comments(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _without_comments(text: str) -> str:
    """Drop `//` comments outside strings so the overlay file can document itself."""
    out: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            escaped = char == "\\" and not escaped
            if char == '"' and not escaped:
                in_string = False
            elif char != "\\":
                escaped = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("//", index):
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        else:
            out.append(char)
        index += 1
    return "".join(out)


def setting[T](key: str, fallback: T) -> T:
    """Dotted lookup in the overlay's defaults.json, e.g. setting("tts.voice", "").

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
