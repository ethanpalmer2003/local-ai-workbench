"""The files a check reads: maintained Python, Markdown and batch sources."""

import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg

EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", "state", "output", "old", "retired", "comfyui-archive"}


def tracked_files() -> list[Path]:
    """Every file Git tracks, whatever its type; placement rules read this list."""
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=project_cfg.BASE_DIR, capture_output=True, check=False, text=True
    )
    if result.returncode:
        return []
    return [project_cfg.BASE_DIR / name for name in result.stdout.split("\0") if name]


def maintained_files() -> list[Path]:
    # - root documents are included so document placement can reject them
    files = sorted(project_cfg.BASE_DIR.glob("*.md"))
    for root in (
        project_cfg.SCRIPTS_DIR,
        project_cfg.BAT_DIR,
        project_cfg.BASE_DIR / "notes",
        project_cfg.BASE_DIR / ".agents",
    ):
        pending = [root]
        while pending:
            for path in pending.pop().iterdir():
                if path.is_junction() or path.is_symlink():
                    continue
                if path.is_dir() and path.name not in EXCLUDED:
                    pending.append(path)
                elif path.is_file() and path.suffix in (".py", ".md", ".bat"):
                    files.append(path)
    return files
