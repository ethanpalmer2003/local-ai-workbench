"""What this checkout has changed since its upstream branch.

One owner for the answer, because the review gate, the formatter and the test scope all narrow
their work to it. The working tree counts, and so does a commit made but not pushed, since that is
still unreviewed work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg


def git(*args: str, root: Path | None = None) -> str:
    """The command's stdout, or an empty string when git fails; callers treat that as no evidence."""
    base = project_cfg.BASE_DIR if root is None else root
    result = subprocess.run(["git", "-C", str(base), *args], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def committed_paths(root: Path | None = None) -> list[str]:
    """The paths HEAD's commit touched, which is what a post-commit hook has to judge."""
    lines = git("show", "--name-only", "--pretty=format:", "HEAD", root=root).splitlines()
    return sorted({line.strip() for line in lines if line.strip()})


def changed_paths(root: Path | None = None) -> list[str]:
    """Every path changed since upstream, working tree included; a rename gives both sides."""
    paths: list[str] = []
    for line in git("status", "--porcelain", root=root).splitlines():
        body = line[3:].strip().strip('"')
        if body:
            paths.extend(part.strip().strip('"') for part in body.split(" -> "))
    paths.extend(
        path for path in git("diff", "--name-only", "@{upstream}...HEAD", root=root).splitlines() if path.strip()
    )
    return sorted(set(paths))
