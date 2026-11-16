"""One vocabulary for the text files the review checks read; a new suffix is added here."""

import subprocess
from pathlib import Path

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


def is_text(path: str) -> bool:
    """Whether this path is text we write; generated evidence is ignored by git, not by suffix."""
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def tracked_text_files(root: Path, skip: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Every tracked file whose content is text we write, minus the check's own fixtures."""
    result = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True)
    # - a deletion is still in the index until it is committed; skip files the tree no longer has
    return [
        path
        for path in result.stdout.splitlines()
        if path and is_text(path) and path not in skip and (root / path).is_file()
    ]
