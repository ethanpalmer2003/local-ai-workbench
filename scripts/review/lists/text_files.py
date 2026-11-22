"""One vocabulary for the text files the review checks read; a new suffix is added here."""

import argparse
import re
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
# - the pinned corpus quotes third-party transcript text verbatim, so its references are data, not our prose
CORPUS_FILE = "scripts/config/benchmarks/language_corpus.json"
REFERENCE_VALUE = re.compile(r'("reference"\s*:\s*")([^"\\]*(?:\\.[^"\\]*)*)(")')


def mask_corpus_references(path: str, text: str) -> str:
    """Blank quoted corpus references, keeping every line and column exactly where it was."""
    if path != CORPUS_FILE:
        return text
    return REFERENCE_VALUE.sub(lambda match: match.group(1) + "x" * len(match.group(2)) + match.group(3), text)


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


def git_root() -> Path:
    """The repository root git reports, which a text check resolves its paths against."""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    return Path(top.stdout.strip())


def text_check_targets(
    argv: list[str] | None, description: str | None, skip: set[str] | frozenset[str] = frozenset()
) -> tuple[Path, list[str]]:
    """The repository root and the files to scan: the paths given, or every tracked text file.

    The two text checks read the same arguments and the same default set, so their entry point is owned
    once; a file a check must not scan itself is dropped whether it was named or discovered.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("paths", nargs="*", help="files to check (default: every tracked text file)")
    args = parser.parse_args(argv)
    root = git_root()
    if args.paths:
        # - an imported patch keeps the upstream prose it carries, so only our own text suffixes are read
        return root, [path for path in args.paths if path not in skip and is_text(path)]
    return root, tracked_text_files(root, skip)
