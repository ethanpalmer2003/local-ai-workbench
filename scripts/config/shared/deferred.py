"""What kind of thing is parked, and the records that name each parked thing."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

RECORDS_PATH = Path(__file__).with_name("deferred.yaml")
FIELDS = ("thing", "kind", "revisit", "source")


class DeferredKind(str, Enum):
    """A parked thing is a weight, an install, a build, a table row, a platform, or a task."""

    MODEL = "model"
    FRAMEWORK = "framework"
    BUILD = "build"
    ROW = "row"
    RUNTIME = "runtime"
    WORK = "work"


@dataclass(frozen=True)
class ParkedWork:
    """One thing that cannot start yet, and what would change that."""

    thing: str
    kind: DeferredKind
    revisit: str
    source: str
    reason: str | None = None
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
    reason = str(raw["reason"]) if raw.get("reason") else None
    subject = str(raw["subject"]) if raw.get("subject") else None
    if subject is not None and reason is None:
        raise ValueError(f"Parked work {index} names a capability row and needs its reason")
    return ParkedWork(
        thing=str(raw["thing"]),
        kind=DeferredKind(kind),
        revisit=str(raw["revisit"]),
        source=str(raw["source"]),
        reason=reason,
        subject=subject,
    )


def records() -> list[ParkedWork]:
    """Every parked record, validated so a typo cannot pass as a kind."""
    raw = yaml.safe_load(RECORDS_PATH.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError("Parked work must be a list")
    return [_entry(item, index) for index, item in enumerate(raw, start=1)]


def for_subject(subject: str) -> ParkedWork | None:
    """The record a capability row names, or None when the row is judged normally."""
    return next((entry for entry in records() if entry.subject == subject), None)
