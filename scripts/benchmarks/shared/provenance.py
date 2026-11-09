"""Recorded identity for a long run: the builds, weights, settings and corpus behind a number.

A timing without this cannot be compared later or marked stale, so every opt-in run records the
workspace commit, each framework revision, each model file, the effective settings and the corpus
revision plus manifest hash.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers.runtime.execution_context import execution_context


def git_state(path: Path) -> dict[str, Any]:
    """Commit and dirty flag for a checkout, or nulls when the folder is not its own repository."""
    try:
        top = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
        # - a plain folder inside the workspace checkout must not borrow the workspace commit
        if not top or Path(top).resolve() != Path(path).resolve():
            return {"commit": None, "dirty": None}
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True, timeout=60, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}
    return {"commit": commit or None, "dirty": bool(status.strip())}


def workspace_state() -> dict[str, Any]:
    return {"path": str(project_cfg.BASE_DIR), **git_state(project_cfg.BASE_DIR)}


def framework_state(key: str) -> dict[str, Any]:
    """Identity of one installed framework; the folder's own repository decides the commit."""
    directory = project_cfg.component(key).framework_dir
    return {"key": key, "dir": str(directory), **git_state(directory)}


def file_identity(label: str, path: Path) -> dict[str, Any]:
    """Weight identity that survives a rename: exact size and modification time."""
    if not path.is_file():
        return {"label": label, "path": str(path), "present": False}
    stat = path.stat()
    return {
        "label": label,
        "path": str(path),
        "present": True,
        "bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
    }


def corpus_state(identity: dict[str, Any], root: Path | None) -> dict[str, Any]:
    """Corpus identity plus the downloaded-evidence file the fetcher writes beside the audio."""
    state = dict(identity)
    record = root / "download.json" if root is not None else None
    state["downloaded"] = json.loads(record.read_text(encoding="utf-8")) if record and record.is_file() else None
    return state


def block(
    *,
    subject: str,
    config: dict[str, Any],
    frameworks: list[dict[str, Any]],
    models: list[dict[str, Any]],
    corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The provenance every long run writes; keys stay stable so a later run can be compared."""
    return {
        "subject": subject,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "execution_context": dict(execution_context()),
        "workspace": workspace_state(),
        "frameworks": frameworks,
        "models": models,
        "config": config,
        "corpus": corpus,
    }


def digest(value: Any) -> str:
    """Stable short hash of a settings mapping, so two runs can be diffed by settings alone."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]
