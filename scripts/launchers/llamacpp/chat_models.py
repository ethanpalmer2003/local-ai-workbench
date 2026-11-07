"""Allowlisted local chat GGUF choices; never accept a browser-supplied file path."""

from pathlib import Path

from scripts.config import models
from scripts.launchers import launcher_config as cfg


def default_id() -> str:
    return cfg.LANGUAGE_PRACTICE.llm_model


def catalog():
    return [
        {
            "id": row.label,
            "label": row.path.stem,
            "available": row.path.is_file(),
            "reason": "" if row.path.is_file() else "Model file is not installed",
        }
        for row in models.MODELS
        if "chat" in row.roles and cfg.LANGUAGE_PRACTICE.framework in row.runtimes
    ]


def path(model_id: str | None = None) -> Path:
    key = model_id or default_id()
    if not any(row["id"] == key for row in catalog()):
        raise ValueError("Unknown chat model; choose a registered llama.cpp GGUF")
    return models.path(key)
