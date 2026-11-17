"""Text shaping for speech: number spelling, cleaning and the speech/silence decision."""

import re


def norm_key(k):
    """Normalize an audio id/filename stem: strips '[tag]' prefix and '.0b2' style suffixes."""
    k = str(k).strip()
    m = re.match(r"^(?:\[[^\]]+\])?([0-9A-Fa-f]+)(?:\.[0-9A-Fa-f]+)?(?:[-_].*)?$", k)
    return (m[1] if m else k).lower()


_TYPO = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "})
_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def int_to_words(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        return f"{_ONES[n // 100]} hundred" + (f" {int_to_words(n % 100)}" if n % 100 else "")
    for size, name in ((10**6, "million"), (1000, "thousand")):
        if n >= size:
            head = f"{int_to_words(n // size)} {name}"
            return head + (f" {int_to_words(n % size)}" if n % size else "")
    return str(n)


def spell_numbers(s):
    """Spell plain integers (not 3.5, 1,000, 2B, 1st) so the text matches what is spoken."""
    return re.sub(r"(?<![\w.,])\d{1,9}(?!\w|[.,]\d)", lambda m: int_to_words(int(m[0])), s)


def clean_text(s):
    """Normalize a transcript for voice cloning: no filename underscores, plain punctuation,
    no symbols/emoji/tags, collapsed repeats, digits spelled out. Stage directions like
    '(sniffs)' are kept here and handled by is_speech() instead."""
    s = str(s).replace("_", "").translate(_TYPO).replace("\u2026", "...")
    s = re.sub(r"<[^>]*>", " ", s)
    s = re.sub(r"[*~#^|\\\U0001F300-\U0001FAFF\u2600-\u27BF]", " ", s)
    s = re.sub(r"[!?]{2,}", lambda m: "?" if "?" in m[0] else "!", s)
    s = re.sub(r"\.{4,}", "...", s)
    s = spell_numbers(s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


MIN_WORDS = 3
MAX_FILLER_RATIO = 0.4
_STAGE_DIRECTION = re.compile(r"[(\[][^)\]]*[)\]]")
_FILLER = re.compile(
    r"^(?:h+m+|m+|u+h+m*|u+m+|a+h+|o+h+|e+r+m*|g+a+h+|h+a+h+|h+u+h+|u+g+h+|c+o+u+g+h+|s+i+g+h+|g+r+o+a+n+|g+r+u+n+t+|h+e+h+e+|s)$",
    re.IGNORECASE,
)


def is_speech(text):
    """True if a transcript looks like real speech worth cloning from.
    Rejects stage directions ('(sniffs)'), clips under MIN_WORDS words, and mostly-filler clips
    (coughs, 'hmm', grunts)."""
    t = str(text).strip()
    if not t or _STAGE_DIRECTION.search(t):
        return False
    words = re.findall(r"[A-Za-z0-9']+", t)
    if len(words) < MIN_WORDS:
        return False
    return sum(bool(_FILLER.match(w)) for w in words) / len(words) <= MAX_FILLER_RATIO


def get_text(files):
    text = {}
    for f in files:
        m = re.match(r"^(.+?)-(.+)$", f.stem)
        if m and m[2].strip() and not re.match(r"^\s*\(", m[2]):
            cleaned = clean_text(m[2])
            if cleaned:
                text[norm_key(m[1])] = cleaned
    return text
