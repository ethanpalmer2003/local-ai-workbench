"""Resolve `{AI_ROOT}` in tracked native configs; engines need real absolute paths."""

import json
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg

PLACEHOLDER = "{AI_ROOT}"


def resolve_text(text: str) -> str:
    return text.replace(PLACEHOLDER, project_cfg.BASE_DIR.as_posix())


def load_text(path: Path) -> str:
    return resolve_text(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> Any:
    return json.loads(load_text(path))


def materialize(source: Path, folder: str = "configs") -> Path:
    """Write a resolved copy under state/generated; native programs cannot read a placeholder."""
    target = project_cfg.component("shared").generated_dir / folder / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    text = load_text(source)
    try:
        current = target.read_text(encoding="utf-8") if target.is_file() else None
    except OSError:
        current = None
    if current != text:
        target.write_text(text, encoding="utf-8")
    return target
