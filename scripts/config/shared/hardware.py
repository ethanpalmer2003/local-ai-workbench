"""The adapters this machine has, so an engine can pin itself to the discrete one."""

import json
from pathlib import Path

HARDWARE_PATH = Path(__file__).with_name("hardware.json")


def read() -> dict[str, str]:
    """The tracked adapter names; a new host edits this file rather than the launchers."""
    raw = json.loads(HARDWARE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Hardware must be a mapping")
    return {str(key): str(value) for key, value in raw.items()}


def discrete_gpu() -> str:
    """The adapter name every engine should select; the integrated one is never a substitute."""
    return read()["discrete_gpu"]
