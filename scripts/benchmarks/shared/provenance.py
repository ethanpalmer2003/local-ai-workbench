"""Recorded identity for a long run: the builds, weights, settings and corpus behind a number.

A timing without this cannot be compared later or marked stale, so every opt-in run records the
workspace commit, each framework revision, each model file, the effective settings and the corpus
revision plus manifest hash.
"""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from scripts.config import project_config as project_cfg
from scripts.launchers.runtime.execution_context import ExecutionContext, execution_context
from scripts.shared import staleness

SHARED_DIR = Path(__file__).resolve().parent


class GitState(TypedDict):
    """A checkout that may be absent, so nulls replace a commit instead of an error."""

    commit: str | None
    dirty: bool | None


class WorkspaceState(GitState):
    path: str


class BinaryState(TypedDict):
    """What changes when a release zip replaces an executable."""

    bytes: int
    modified: str


class FrameworkState(GitState):
    key: str
    dir: str
    binaries: dict[str, BinaryState]


class ModelIdentity(TypedDict):
    """Weight identity; `bytes` and `modified` are absent when the file is not there."""

    label: str
    path: str
    present: bool
    bytes: NotRequired[int]
    modified: NotRequired[str]


class ProvenanceBlock(TypedDict):
    """The block a long run records; keys stay stable so a later run can compare."""

    subject: str
    recorded_at: str
    execution_context: ExecutionContext
    workspace: WorkspaceState
    producer: dict[str, str]
    frameworks: list[FrameworkState]
    models: list[ModelIdentity]
    config: dict[str, Any]
    corpus: dict[str, Any] | None


# - The executable each engine actually runs; a release zip replaces these first
ENGINE_BINARIES = ("llama-server.exe", "llama-bench.exe", "audiocpp_server.exe", "sd-server.exe")


def git_state(path: Path) -> GitState:
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


def workspace_state() -> WorkspaceState:
    return {"path": str(project_cfg.BASE_DIR), **git_state(project_cfg.BASE_DIR)}


def engine_binaries(directory: Path) -> dict[str, BinaryState]:
    """Identity of the engine executables an install keeps, so a swapped binary release is visible.

    Releases are zips unpacked over the install folder, and none of them is a git checkout, so size
    and modification time are the only evidence that the build behind a number changed.
    """
    if not directory.is_dir():
        return {}
    found: dict[str, BinaryState] = {}
    for pattern in ("*", "*/*"):
        for path in sorted(directory.glob(pattern)):
            if not path.is_file() or path.name not in ENGINE_BINARIES:
                continue
            try:
                stat = path.stat()
            except OSError:
                # - a binary replaced between the glob and the read is the change this records
                continue
            found[path.relative_to(directory).as_posix()] = {
                "bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
            }
    return found


def framework_state(key: str) -> FrameworkState:
    """Identity of one installed framework: its commit when it has one, and its engine binaries."""
    directory = project_cfg.component(key).framework_dir
    return {"key": key, "dir": str(directory), **git_state(directory), "binaries": engine_binaries(directory)}


def changed_binaries(recorded: dict[str, BinaryState], current: dict[str, BinaryState]) -> list[str]:
    """Recorded engine binaries a later run would load in a different build."""
    return sorted(name for name, state in recorded.items() if current.get(name) != state)


def file_identity(label: str, path: Path) -> ModelIdentity:
    """Weight identity that survives a rename: exact size and modification time."""
    try:
        stat = path.stat()
    except OSError:
        # - absent, or removed between the caller naming it and this read; either way there is no weight
        return {"label": label, "path": str(path), "present": False}
    if not path.is_file():
        return {"label": label, "path": str(path), "present": False}
    return {
        "label": label,
        "path": str(path),
        "present": True,
        "bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
    }


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
                return staleness.manifest([resolved], project_cfg.BASE_DIR)
        frame = frame.f_back
    return {}


def changed_manifest(recorded: dict[str, str]) -> list[str]:
    """Recorded source files whose content differs now, or that have since been removed."""
    return sorted(
        name
        for name, digest in recorded.items()
        if not (project_cfg.BASE_DIR / name).is_file()
        or staleness.content_digest(project_cfg.BASE_DIR / name) != digest
    )


def corpus_state(identity: dict[str, Any], root: Path | None) -> dict[str, Any]:
    """Corpus identity plus the downloaded-evidence file the fetcher writes beside the audio."""
    state = dict(identity)
    record = root / "download.json" if root is not None else None
    downloaded: dict[str, Any] | None = None
    if record is not None and record.is_file():
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        downloaded = payload if isinstance(payload, dict) else None
    state["downloaded"] = downloaded
    return state


def block(
    *,
    subject: str,
    config: dict[str, Any],
    frameworks: list[FrameworkState],
    models: list[ModelIdentity],
    corpus: dict[str, Any] | None = None,
) -> ProvenanceBlock:
    """The provenance every long run writes; keys stay stable so a later run can be compared."""
    return {
        "subject": subject,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "execution_context": execution_context(),
        "workspace": workspace_state(),
        "producer": producer_state(),
        "frameworks": frameworks,
        "models": models,
        "config": config,
        "corpus": corpus,
    }


def digest(value: object) -> str:
    """Stable short hash of a settings mapping, so two runs can be diffed by settings alone."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]
