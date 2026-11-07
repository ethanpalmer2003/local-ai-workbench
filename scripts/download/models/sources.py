"""Hugging Face file source URLs shared by both download interfaces."""

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class HubFile:
    repo_id: str
    filename: str
    revision: str


def parse_url(url: str) -> HubFile:
    """Read a Hub file URL, preserving its revision and excluding query parameters."""
    parsed = urlsplit(url)
    match = re.fullmatch(r"/([^/]+/[^/]+)/(?:blob|resolve|tree)/([^/]+)/(.+)", parsed.path)
    if parsed.hostname != "huggingface.co" or not match:
        raise ValueError(f"Invalid HuggingFace URL:\n{url}")
    return HubFile(unquote(match.group(1)), unquote(match.group(3)), unquote(match.group(2)))
