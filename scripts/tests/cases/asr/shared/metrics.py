"""Shared ASR text normalization and word-error metrics."""

import re
import unicodedata
from typing import Any


def pooled_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    words = sum(row["reference_words"] for row in rows)
    characters = sum(row["reference_characters"] for row in rows)
    return {
        "samples": len(rows),
        "pooled_wer": sum(round(row["wer"] * row["reference_words"]) for row in rows) / words if words else None,
        "pooled_cer": sum(round(row["cer"] * row["reference_characters"]) for row in rows) / characters
        if characters
        else None,
    }


def words(text: str) -> list[str]:
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(char)
    )
    return ["practice" if word == "practice" else word for word in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", normalized)]


def word_errors(reference: str, hypothesis: str) -> dict[str, Any]:
    expected, actual = words(reference), words(hypothesis)
    previous = list(range(len(actual) + 1))
    for index, left in enumerate(expected, 1):
        current = [index]
        for column, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (left != right)))
        previous = current
    count = previous[-1]
    return {"word_errors": count, "reference_words": len(expected), "wer": count / len(expected) if expected else None}


def distance(expected: list[str], actual: list[str]) -> int:
    previous = list(range(len(actual) + 1))
    for index, left in enumerate(expected, 1):
        current = [index]
        for column, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (left != right)))
        previous = current
    return previous[-1]


def unicode_errors(reference: str, hypothesis: str) -> dict[str, Any]:
    """Accent-sensitive WER/CER; CER is preferable for scripts without word spaces."""
    texts = [unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'") for text in (reference, hypothesis)]
    expected, actual = [re.findall(r"[^\W_]+(?:'[^\W_]+)*", text) for text in texts]
    ref_chars, hyp_chars = [[char for char in text if char.isalnum()] for text in texts]
    return {
        "wer": distance(expected, actual) / len(expected) if expected else None,
        "cer": distance(ref_chars, hyp_chars) / len(ref_chars) if ref_chars else None,
        "reference_words": len(expected),
        "reference_characters": len(ref_chars),
    }
