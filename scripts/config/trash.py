"""Move a workspace path into a day folder under trash instead of deleting it."""

import shutil
import time
from datetime import datetime
from pathlib import Path

from scripts.config import project_config as project_cfg


def trash_root() -> Path:
    """The folder holding every dated trash folder; computing it creates nothing."""
    return project_cfg.BASE_DIR / "trash"


def trash_dir(stamp: str | None = None) -> Path:
    """Today's trash folder path (`trash/YYYY-MM-DD`); computing it creates nothing."""
    return (trash_root() / (stamp or datetime.now().strftime("%Y-%m-%d"))).resolve()


def trash_path(name: str) -> Path:
    """A destination inside today's trash folder, created for the caller that names its own entry."""
    destination = trash_dir() / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def archive_path(path: Path, root: Path) -> None:
    """Archive one path under `root` into today's trash folder, refusing anything outside that root."""
    path = path.resolve()
    path.relative_to(root.resolve())
    if path == root.resolve():
        raise ValueError("Cannot archive the containing root")
    if not path.exists():
        return
    if path.is_dir() and not any(path.iterdir()):
        # - an empty directory holds nothing worth keeping, so it is removed rather than archived
        path.rmdir()
        return
    trash = trash_dir()
    destination = trash_path(f"{path.name}-{time.time_ns()}")
    destination.relative_to(trash)
    shutil.move(str(path), str(destination))
