"""Shared TTS text cleanup, with explicitly Breeze 2-specific instructions and events.

- Generic: configured string/regex cleanup and whitespace normalization.
- Breeze 2 TTS only: quote removal, automatic tone instructions, remembered/default
  tones, and optional vocal-event/parenthetical filtering.
- Both streaming and complete-WAV requests use these same rules.
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from scripts.config import inputs
from scripts.launchers import launcher_config as cfg
from scripts.launchers.shared.media import text_processing


@dataclass
class BreezeToneSettings:
    tags_enabled: bool = True
    default_enabled: bool = inputs.setting(
        "chat.tts.instruction_enabled", bool(inputs.setting("chat.tts.instruction", ""))
    )
    default_instruction: str = inputs.setting("chat.tts.instruction", "")
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

    # - parentheticals kept in the spoken text (Breeze vocal events)
    allowed_vocal_events: set[str] = field(
        default_factory=lambda: {
            "(laugh)",
            "(chuckle)",
            "(giggle)",
            "(cry)",
            "(sob)",
            "(whimper)",
            "(groan)",
            "(moan)",
            "(sigh)",
            "(gasp)",
            "(inhale)",
            "(exhale)",
            "(breathe heavily)",
            "(whisper)",
            "(shout)",
            "(scream)",
            "(sing)",
            "(hum)",
            "(stutter)",
            "(pause)",
            "(clear throat)",
            "(clears throat)",
            "(cough)",
            "(coughs)",
            "(sniffle)",
            "(lip smack)",
            "(click tongue)",
            "(yawn)",
            "(sneeze)",
            "(hiccup)",
            "(burp)",
            "(gulp)",
            "(gag)",
            "(grunt)",
            "(scoff)",
            "(snort)",
        }
    )


BREEZE_VOCAL_EVENTS = BreezeVocalEventSettings()


def _trim_to_vocal_event(content: str) -> str | None:
    """Reduce a parenthetical to its bare vocal event when the text contains
    one plus extra words/plural:
    - "giggle softly" -> "(giggle)"
    - "giggles" -> "(giggle)"
    - None if no single event fills the parenthetical"""
    normalized = content.strip().lower()
    # longest event first, so "clears throat softly" prefers
    # "clears throat" over a partial "clears"
    for event in sorted(BREEZE_VOCAL_EVENTS.allowed_vocal_events, key=len, reverse=True):
        base = event.lower().strip().strip("()")  # events carry their own parens
        if normalized == base:
            return None  # already the bare event - keep original
        if normalized == base + "s" or normalized.startswith(base + " ") or normalized.startswith(base + "s "):
            return f"({base})"
    return None


def filter_breeze_vocal_events(text: str) -> str:
    """
    - Vocal-event tags like (laugh) always pass through
    - trim_vocal_events: parenthetical containing a vocal event plus extra
      words/plural is reduced to the bare event ("(giggle softly)" ->
      "(giggle)"); applies in all parentheticals modes
    - Other parentheticals follow BREEZE_VOCAL_EVENTS.parentheticals:
      stripped entirely, unwrapped (parens removed, text kept), or left untouched
    """
    settings = BREEZE_VOCAL_EVENTS
    if not settings.enabled:
        return text

    def handle(match: re.Match[str]) -> str:
        if settings.trim_vocal_events:
            trimmed = _trim_to_vocal_event(match.group(1))
            if trimmed:
                return trimmed
        if match.group(0).lower().strip() in settings.allowed_vocal_events:
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
