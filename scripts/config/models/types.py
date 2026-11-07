"""Shared model registry contract; storage ownership is separate from runtime capabilities."""

from dataclasses import dataclass
from pathlib import Path
from scripts.config import project_config as project_cfg


@dataclass(frozen=True)
class ModelDownload:
    group: str
    label: str
    url: str | None
    destination: str  # Relative to project_cfg.DATA_DIR.
    in_use: bool = False
    notes: str = ""
    sha256: str | None = None
    roles: tuple[str, ...] = ()
    runtimes: tuple[str, ...] = ()  # Candidate routing, not evidence of tested compatibility.
    source_page: str | None = None  # Provenance page; may not be a direct downloadable file.
    filename: str | None = None  # Destination relative to the component's models_dir.
    category: str = ""  # Catalog module key: llms/asr/tts/images.

    @property
    def path(self) -> Path:
        return project_cfg.DATA_DIR / self.destination
