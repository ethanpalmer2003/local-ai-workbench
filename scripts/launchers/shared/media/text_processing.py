"""Shared speech-text cleanup for character and practice; model-specific controls stay in adapters."""

import re

from scripts.launchers import launcher_config as cfg


def strip_emoji(text: str) -> str:
    """Remove Unicode pictographs/sequences without deleting non-BMP language characters."""
    import regex

    pattern = (
        r"[0-9#*]\ufe0f?\u20e3|"
        r"\p{Regional_Indicator}+|"
        r"\u200d?\p{Extended_Pictographic}[\ufe0e\ufe0f]?\p{Emoji_Modifier}?"
        r"(?:\u200d\p{Extended_Pictographic}[\ufe0e\ufe0f]?\p{Emoji_Modifier}?)*"
        r"[\U000e0020-\U000e007f]*\u200d?|"
        r"\p{Emoji_Modifier}|[\ufe0e\ufe0f\u20e3]"
    )
    return regex.sub(pattern, " ", text)


def filter_scripts(text: str, language: str | None) -> str:
    """Speech-only script compatibility; never claim language detection/transliteration."""
    import regex

    code = (language or "").lower().replace("_", "-").split("-")[0]
    scripts = {
        "en": ("Latin",),
        "es": ("Latin",),
        "fr": ("Latin",),
        "it": ("Latin",),
        "pt": ("Latin",),
        "hi": ("Latin", "Devanagari"),
        "ja": ("Latin", "Han", "Hiragana", "Katakana"),
        "zh": ("Latin", "Han"),
    }.get(code)
    if not scripts:
        return text
    allowed = regex.compile("|".join(r"\p{Script_Extensions=" + script + "}" for script in scripts))

    def compatible(match):
        cluster = match.group()
        return " " if regex.search(r"\p{L}", cluster) and not allowed.search(cluster) else cluster

    return regex.sub(r"\X", compatible, text)


def clean_text(text: str, *, language: str | None = None) -> str:
    """One generic owner: emoji, configured replacements/strips, then whitespace."""
    text = strip_emoji(text)
    text = filter_scripts(text, language)
    settings = cfg.SHARED_TTS_TEXT_CLEANUP
    for pattern, replacement in settings.replace_patterns.items():
        text = re.sub(pattern, replacement, text)
    for item in settings.strip_characters:
        text = text.replace(item, "")
    for pattern in settings.strip_patterns:
        text = re.sub(pattern, "", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_speech_payload(payload: dict[str, object], *, language: str | None = None) -> None:
    text = payload.get("input")
    if not isinstance(text, str):
        raise ValueError("Speech input must be a string")
    options = payload.get("options")
    selected = options.get("language") if isinstance(options, dict) else None
    cleaned = clean_text(text, language=selected if isinstance(selected, str) else language)
    if not cleaned:
        raise ValueError("Speech input is empty after text cleanup")
    payload["input"] = cleaned
