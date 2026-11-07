"""Read AudioCpp's editable native JSON base; launch overrides stay in the launcher."""

from pathlib import Path
from typing import Any

from scripts.config import paths
from scripts.config import project_config as project_cfg

CONFIG_PATH = project_cfg.CONFIG_DIR / "audiocpp/server.json"


def read(path: Path | None = None) -> dict[str, Any]:
    return paths.load_json(CONFIG_PATH if path is None else path)
