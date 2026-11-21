"""What kind of thing is parked, why it is parked on this machine, and what would unpark it."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

RECORDS_PATH = Path(__file__).with_name("deferred.yaml")
FIELDS = ("thing", "kind", "cause", "reason", "revisit", "source")


class DeferredKind(str, Enum):
    """A parked thing is a weight, an install, a build, a table row, a platform, or a task."""

    MODEL = "model"
    FRAMEWORK = "framework"
    BUILD = "build"
    ROW = "row"
    RUNTIME = "runtime"
    WORK = "work"


class DeferredCause(str, Enum):
    """Why this host parks it: its numbers, its OS, its GPU vendor, a measured loss, or nothing planned."""

    CAPACITY = "capacity"
    OS = "os"
    VENDOR = "vendor"
    PERFORMANCE = "performance"
    UNPLANNED = "unplanned"


@dataclass(frozen=True)
class ParkedWork:
    """One thing that cannot start yet, why this host parks it, and what would change that."""

    thing: str
    kind: DeferredKind
    cause: DeferredCause
    reason: str
    revisit: str
    source: str
    subject: str | None = None


def _entry(raw: object, index: int) -> ParkedWork:
    if not isinstance(raw, dict):
        raise ValueError(f"Parked work {index} must be a mapping")
    missing = [field for field in FIELDS if not raw.get(field)]
    if missing:
        raise ValueError(f"Parked work {index} is missing: {', '.join(missing)}")
    kind = str(raw["kind"])
    if kind not in {item.value for item in DeferredKind}:
        raise ValueError(f"Parked work {index} has an undeclared kind: {kind}")
    cause = str(raw["cause"])
    if cause not in {item.value for item in DeferredCause}:
        raise ValueError(f"Parked work {index} has an undeclared cause: {cause}")
    return ParkedWork(
        thing=str(raw["thing"]),
        kind=DeferredKind(kind),
        cause=DeferredCause(cause),
        reason=str(raw["reason"]),
        revisit=str(raw["revisit"]),
        source=str(raw["source"]),
        subject=str(raw["subject"]) if raw.get("subject") else None,
    )


def records() -> list[ParkedWork]:
    """Every parked record, validated so a typo cannot pass as a kind or cause."""
    raw = yaml.safe_load(RECORDS_PATH.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError("Parked work must be a list")
    return [_entry(item, index) for index, item in enumerate(raw, start=1)]


def for_subject(subject: str) -> ParkedWork | None:
    """The record a capability row names, or None when the row is judged normally."""
    return next((entry for entry in records() if entry.subject == subject), None)
