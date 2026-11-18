"""What this checkout has changed, in the two sets the two stages need.

One owner for the answer, because the review gate, the formatter and the test scope all narrow their work
to it. Two functions, one per stage:

- `changed_since_head()` is the commit stage: the working tree and index against `HEAD`, so earlier
  unpushed commits do not run again.
- `changed_since_upstream()` is the push stage and a bare run: those paths plus the commits the upstream
  branch lacks, since anything unreviewed is in scope there.
"""

import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg


def git_text(*args: str, root: Path | None = None) -> str:
    """The command's stdout, or an empty string when git fails; callers treat that as no evidence.

    The bytes are decoded as UTF-8 here rather than by the locale, because `git show` returns file
    content: a source file with an accented name or letter is not decodable by every console codec,
    and a reader thread that raises leaves the caller with None instead of text.
    """
    base = project_cfg.BASE_DIR if root is None else root
    result = subprocess.run(["git", "-C", str(base), *args], capture_output=True, check=False)
    return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else ""


def committed_paths(root: Path | None = None) -> list[str]:
    """The paths HEAD's commit touched, which is what a post-commit hook has to judge."""
    lines = git_text("show", "--name-only", "--pretty=format:", "HEAD", root=root).splitlines()
    return sorted({line.strip() for line in lines if line.strip()})


def changed_since_head(root: Path | None = None) -> list[str]:
    """Every path the working tree or the index has changed against `HEAD`; a rename gives both sides."""
    paths: list[str] = []
    for line in git_text("status", "--porcelain", root=root).splitlines():
        body = line[3:].strip().strip('"')
        if body:
            paths.extend(part.strip().strip('"') for part in body.split(" -> "))
    return sorted(set(paths))


def changed_since_upstream(root: Path | None = None) -> list[str]:
    """Every unreviewed path: the working tree against `HEAD`, plus commits the upstream lacks."""
    paths = changed_since_head(root)
    paths.extend(
        path for path in git_text("diff", "--name-only", "@{upstream}...HEAD", root=root).splitlines() if path.strip()
    )
    return sorted(set(paths))
