"""Move a workspace path into trash instead of deleting it."""

import shutil
import time
from pathlib import Path

from scripts.config import project_config as project_cfg


def archive_path(path: Path, root: Path) -> None:
    """Archive one path under `root` into `trash/`, refusing anything outside that root."""
    path = path.resolve()
    path.relative_to(root.resolve())
    if path == root.resolve():
        raise ValueError("Cannot archive the containing root")
    if not path.exists():
        return
    trash = (project_cfg.BASE_DIR / "trash").resolve()
    trash.mkdir(parents=True, exist_ok=True)
    destination = trash / f"{path.name}-{time.time_ns()}"
    destination.relative_to(trash)
    shutil.move(str(path), str(destination))
