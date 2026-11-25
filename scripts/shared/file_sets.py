"""The file sets the review checks read, from one listing mechanism.

One `git ls-files` helper answers every listing, so the four sets cannot drift apart: the tracked
set holds every file git lists, the maintained set holds the Python, Markdown and batch sources a
check reads, the text set holds every tracked file carrying prose or config we write, and the changed
set holds the working tree against `HEAD` plus the commits the upstream branch lacks.

The check-specific entry wrappers stay with their checks: `sources.check_targets` and
`text_files.text_check_targets` narrow these sets to one run's arguments.
"""

import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg

# - parked trees hold code kept for reference: not maintained, not imported, not checked
EXCLUDED = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "state",
    "output",
    "old",
    "retired",
    "parked",
    "comfyui-archive",
}

TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cjs",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".jinja",
    ".js",
    ".json",
    ".kcpps",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}


class GitError(RuntimeError):
    """A git command failed, so there is no answer rather than an empty one."""


class NoUpstreamError(RuntimeError):
    """This branch has no upstream ref, so there is nothing to compare against."""


def git_root() -> Path:
    """The repository root git reports, which a text check resolves its paths against."""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    return Path(top.stdout.strip())


def git_text(*args: str, root: Path | None = None) -> str:
    """The command's stdout, raising `GitError` when git fails.

    The bytes are decoded as UTF-8 here rather than by the locale, because `git show` returns file
    content: a source file with an accented name or letter is not decodable by every console codec, and
    a reader thread that raises leaves the caller with None instead of text.
    """
    base = project_cfg.BASE_DIR if root is None else root
    result = subprocess.run(["git", "-C", str(base), *args], capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip() or f"exit {result.returncode}"
        raise GitError(f"git {' '.join(args)}: {detail}")
    return result.stdout.decode("utf-8", errors="replace")


def git_text_or_none(*args: str, root: Path | None = None) -> str | None:
    """The command's stdout, or None when git fails; callers read that as no evidence."""
    try:
        return git_text(*args, root=root)
    except GitError:
        return None


def git_ls_files(root: Path | None = None) -> list[str]:
    """Every path git lists under `root`, whatever its type; the one listing every set reads.

    Raises `GitError` when git fails, because a broken read is not the same answer as an empty one;
    `tracked_files` reads that failure as an empty list.
    """
    base = project_cfg.BASE_DIR if root is None else root
    result = subprocess.run(["git", "-C", str(base), "ls-files", "-z"], capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip() or f"exit {result.returncode}"
        raise GitError(f"git ls-files: {detail}")
    return [name for name in result.stdout.decode("utf-8", errors="replace").split("\0") if name]


def tracked_files() -> list[Path]:
    """Every file Git tracks, whatever its type; placement rules read this list."""
    try:
        names = git_ls_files()
    except GitError:
        return []
    return [project_cfg.BASE_DIR / name for name in names]


def maintained_files() -> list[Path]:
    """Every Python, Markdown and batch source the checks read, parked trees excluded."""
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


def is_text(path: str) -> bool:
    """Whether this path is text we write; generated evidence is ignored by git, not by suffix."""
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def tracked_text_files(root: Path, skip: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Every tracked file whose content is text we write, minus the check's own fixtures."""
    # - a deletion is still in the index until it is committed; skip files the tree no longer has
    return [path for path in git_ls_files(root) if is_text(path) and path not in skip and (root / path).is_file()]


def upstream_known(root: Path | None = None) -> bool:
    """Whether this branch has an upstream ref, which an empty change set cannot tell you."""
    return bool((git_text_or_none("rev-parse", "--abbrev-ref", "@{upstream}", root=root) or "").strip())


def changed_since_head(root: Path | None = None) -> list[str]:
    """Every path the working tree or the index has changed against `HEAD`; a rename gives both sides."""
    paths: list[str] = []
    for line in git_text("status", "--porcelain", root=root).splitlines():
        body = line[3:].strip().strip('"')
        if body:
            paths.extend(part.strip().strip('"') for part in body.split(" -> "))
    return sorted(set(paths))


def changed_since_upstream(root: Path | None = None) -> list[str]:
    """Every unreviewed path: the working tree against `HEAD`, plus commits the upstream lacks.

    Raises NoUpstreamError when the branch has none, which is a different answer from an empty list.
    """
    if not upstream_known(root):
        raise NoUpstreamError
    paths = changed_since_head(root)
    paths.extend(
        path for path in git_text("diff", "--name-only", "@{upstream}...HEAD", root=root).splitlines() if path.strip()
    )
    return sorted(set(paths))
