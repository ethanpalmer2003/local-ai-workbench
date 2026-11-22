"""Breeze TTS 2 vocal events: the vendor's own tag spellings, kept in one data file.

The Breeze audio-tags page owns these spellings, so the adapter reads them from the JSON beside this module
instead of carrying a hard-coded list the vendor can outgrow. Only the English tags are recorded: Breeze 2
runs here as an English voice, not as a language-practice model. Refresh the file by re-reading
https://docs.breezeblue.ai/guides/audio-tags, updating the JSON, and rerunning the audiocpp test cases.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

EVENTS_PATH = Path(__file__).with_name("breeze-tts-events.json")


@dataclass(frozen=True)
class VocalEvent:
    """One documented event: its canonical name, the vendor's category and every accepted spelling."""

    canonical: str
    category: str
    tags: tuple[str, ...]


@cache
def events() -> tuple[VocalEvent, ...]:
    """Every documented English event, in the order the vendor groups them."""
    payload = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    return tuple(
        VocalEvent(str(row["canonical"]), str(row["category"]), tuple(str(tag) for tag in row["tags"]))
        for row in payload["events"]
    )


@cache
def tags() -> frozenset[str]:
    """Every accepted spelling, parenthesized exactly as the model receives it."""
    return frozenset(tag for event in events() for tag in event.tags)
