"""Recorded identity for a long run: the builds, weights, settings and corpus behind a number.

A timing without this cannot be compared later or marked stale, so every opt-in run records the
workspace commit, each framework revision, each model file, the effective settings and the corpus
revision plus manifest hash.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers.runtime.execution_context import execution_context

SHARED_DIR = Path(__file__).resolve().parent


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


def content_digest(path: Path) -> str:
    """SHA256 of a file's bytes: what a generated artifact must compare to notice a changed source."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(paths: list[Path], root: Path) -> dict[str, str]:
    """Content digest per file relative to `root`: the cache key a generated artifact compares."""
    return {path.relative_to(root).as_posix(): content_digest(path) for path in paths}


def changed_files(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    """Files whose content differs from a recorded manifest, or that are new."""
    return sorted(path for path, digest in current.items() if previous.get(path) != digest)


def producer_state() -> dict[str, str]:
    """Digest of the script that produced a number: the nearest caller outside the shared helpers.

    A run calls in from its own module, so the file a reader would have to change to change the
    number is found without every producer passing its own path.
    """
    frame = sys._getframe(1)
    while frame is not None:
        path = Path(str(frame.f_globals.get("__file__") or ""))
        if path.suffix == ".py" and path.is_file():
            resolved = path.resolve()
            if resolved.is_relative_to(project_cfg.BASE_DIR) and SHARED_DIR not in resolved.parents:
                return source_manifest([resolved], project_cfg.BASE_DIR)
        frame = frame.f_back
    return {}


def changed_manifest(recorded: dict[str, str]) -> list[str]:
    """Recorded source files whose content differs now, or that have since been removed."""
    return sorted(
        name
        for name, digest in recorded.items()
        if not (project_cfg.BASE_DIR / name).is_file() or content_digest(project_cfg.BASE_DIR / name) != digest
    )


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
        "producer": producer_state(),
        "frameworks": frameworks,
        "models": models,
        "config": config,
        "corpus": corpus,
    }


def digest(value: Any) -> str:
    """Stable short hash of a settings mapping, so two runs can be diffed by settings alone."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]
