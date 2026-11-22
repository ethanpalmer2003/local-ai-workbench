"""Shared TTS text cleanup, with explicitly Breeze 2-specific instructions and events.

- Generic: configured string/regex cleanup and whitespace normalization.
- Breeze 2 TTS only: quote removal, automatic tone instructions, remembered/default
  tones, and optional vocal-event/parenthetical filtering.
- Both streaming and complete-WAV requests use these same rules.
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from scripts.config import local_overlay
from scripts.config.audiocpp import tts_events
from scripts.launchers import launcher_config as cfg
from scripts.launchers.shared.media import text_processing


@dataclass
class BreezeToneSettings:
    tags_enabled: bool = True
    default_enabled: bool = local_overlay.setting(
        "chat.tts.instruction_enabled", bool(local_overlay.setting("chat.tts.instruction", ""))
    )
    default_instruction: str = local_overlay.setting("chat.tts.instruction", "")
    guidance_scale: float = 1.0

    tag_pattern: str = r"\[(?:Tone|Mood|Instruction|Voice):\s*([^\]]+)\]"


BREEZE_TONES = BreezeToneSettings()


class ToneState:
    """
    - Most recent [Tone: ...] instruction; chunks without a tag inherit it
    """

    def __init__(self):
        self.last: str | None = None


tone_state = ToneState()


def apply_breeze_tone(payload: dict[str, object]) -> None:
    """Explicit client instruction > current tag > last tag > enabled default."""
    forwarded_tag = payload.pop("_tone_tag", None)
    text = payload.get("input")
    if not isinstance(text, str):
        return
    tones = BREEZE_TONES
    match = re.search(tones.tag_pattern, text, re.IGNORECASE)
    tag = forwarded_tag if isinstance(forwarded_tag, str) else match.group(1).strip() if match else None
    payload["input"] = re.sub(tones.tag_pattern, "", text, flags=re.IGNORECASE)
    options = payload.get("options")
    options = dict(options) if isinstance(options, dict) else {}
    if tones.tags_enabled:
        if tag:
            tone_state.last = tag
        if isinstance(options.get("instruction"), str):
            tone_state.last = options["instruction"]
        inherited = tone_state.last
    else:
        tone_state.last = None
        inherited = None
    if options.get("instruction") is None:
        instruction = inherited or tones.default_instruction or None
        # - An empty instruction prevents backend defaults from re-enabling a disabled tone.
        options["instruction"] = instruction or ""
    if options.get("guidance_scale") is None:
        options["guidance_scale"] = tones.guidance_scale
    payload["options"] = options


class BreezeParenMode(str, Enum):
    STRIP = "strip"  # non-vocal parentheticals removed entirely
    UNWRAP = "unwrap"  # non-vocal parentheticals lose their parens, text kept
    KEEP = "keep"  # parentheticals untouched


@dataclass
class BreezeVocalEventSettings:
    enabled: bool = True

    # what happens to parentheticals that aren't known vocal events
    parentheticals: BreezeParenMode = BreezeParenMode.UNWRAP

    # parenthetical containing a vocal event plus extra words is reduced to
    # the bare event
    # - "(giggle softly)" -> "(giggle)"
    # - "(giggles)" -> "(giggle)"
    # - applies in all parentheticals modes
    trim_vocal_events: bool = True

    # - parentheticals kept in the spoken text (Breeze vocal events), from the vendor's tag table
    allowed_vocal_events: frozenset[str] = field(default_factory=tts_events.tags)


BREEZE_VOCAL_EVENTS = BreezeVocalEventSettings()


def _vendor_vocal_event(content: str) -> str | None:
    """The vendor's tag for a parenthetical that names a vocal event, however it was spelled.

    - a known event, singular or plural: "giggle" and "giggles" both become "(giggles)"
    - one plus extra words: "giggle softly" and "giggles softly" also become "(giggles)"
    - None when no event fills the parenthetical, so the caller's parenthetical rule decides
    """
    normalized = content.strip().lower()
    events = tts_events.tag_map()
    if f"({normalized})" in events:
        return events[f"({normalized})"]
    # longest event first, so "clears throat softly" prefers "clears throat" over a partial "clears"
    for spelling in sorted(events, key=len, reverse=True):
        base = spelling.strip("()")
        if normalized.startswith(base + " ") or normalized.startswith(base + "s "):
            return events[spelling]
    return None


def filter_breeze_vocal_events(text: str) -> str:
    """
    - A known event is sent as the vendor's tag: "(giggle)" and "(giggles)" both become "(giggles)"
    - trim_vocal_events: an event plus extra words or a plural is reduced to that tag
      ("(giggle softly)" -> "(giggles)"); applies in all parentheticals modes
    - Other parentheticals follow BREEZE_VOCAL_EVENTS.parentheticals:
      stripped entirely, unwrapped (parens removed, text kept), or left untouched
    """
    settings = BREEZE_VOCAL_EVENTS
    if not settings.enabled:
        return text

    def handle(match: re.Match[str]) -> str:
        spelling = match.group(0).lower().strip()
        event = _vendor_vocal_event(match.group(1))
        if event is not None and (settings.trim_vocal_events or spelling in settings.allowed_vocal_events):
            return event
        if spelling in settings.allowed_vocal_events:
            return match.group(0)
        if settings.parentheticals == BreezeParenMode.KEEP:
            return match.group(0)
        return match.group(1) if settings.parentheticals == BreezeParenMode.UNWRAP else ""

    return re.sub(r"\(([^)]+)\)", handle, text)


def clean_text(payload: dict[str, object]) -> tuple[str | None, float]:
    payload.pop("_tone_tag", None)
    text = payload.get("input")
    if not isinstance(text, str):
        return None, 0.0
    cleaned = text
    if payload.get("model") in cfg.BREEZE_MODELS:
        cleaned = filter_breeze_vocal_events(cleaned).replace('"', "")
    options = payload.get("options")
    language = options.get("language") if isinstance(options, dict) else None
    cleaned = text_processing.clean_text(cleaned, language=language if isinstance(language, str) else None)
    if not cleaned:
        return None, 0.0
    return cleaned, 0.0
