"""One spelling for a path in a message a person reads.

Relative to the repository where the file is inside it, absolute otherwise, and always with forward
slashes so a finding looks the same in a terminal, a test assertion and a chat window.
"""

from pathlib import Path

from scripts.config import project_config as project_cfg


def display_path(path: Path) -> str:
    """The path as a report prints it: repo-relative when it can be, absolute when it cannot."""
    if path.is_relative_to(project_cfg.BASE_DIR):
        return path.relative_to(project_cfg.BASE_DIR).as_posix()
    return path.as_posix()
