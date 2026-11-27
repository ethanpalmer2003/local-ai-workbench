"""Resolve `{AI_ROOT}` in tracked native configs; engines need real absolute paths."""

import json
from pathlib import Path
from typing import Any, cast

from scripts.config import project_config as project_cfg

PLACEHOLDER = "{AI_ROOT}"


def resolve_text(text: str) -> str:
    return text.replace(PLACEHOLDER, project_cfg.BASE_DIR.as_posix())


def load_text(path: Path) -> str:
    return resolve_text(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object; every configuration file here is an object.

    A wrong top-level type is a broken config, so it is raised here where the file is named rather than
    surfacing later as an attribute error in whichever caller read a list.
    """
    payload = json.loads(load_text(path))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must hold a JSON object, not {type(payload).__name__}")
    return cast(dict[str, Any], payload)


def materialize(source: Path, folder: str = "configs") -> Path:
    """Write a resolved copy under the generated root; native programs cannot read a placeholder.

    A file with nothing to resolve is handed over as it is: copying it would add a second copy of the
    same bytes that can only drift from the tracked one.
    """
    text = load_text(source)
    if text == source.read_text(encoding="utf-8"):
        return source
    target = project_cfg.component("shared").generated_dir / folder / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = target.read_text(encoding="utf-8") if target.is_file() else None
    except OSError:
        current = None
    if current != text:
        target.write_text(text, encoding="utf-8")
    return target
