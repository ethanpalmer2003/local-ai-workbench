"""One vocabulary for the text files the review checks read; a new suffix is added here."""

import argparse
import re
from pathlib import Path

from scripts.shared import file_sets

# - the pinned corpus quotes third-party transcript text verbatim, so its references are data, not our prose
CORPUS_FILE = "scripts/config/benchmarks/language_corpus.json"
REFERENCE_VALUE = re.compile(r'("reference"\s*:\s*")([^"\\]*(?:\\.[^"\\]*)*)(")')


def mask_corpus_references(path: str, text: str) -> str:
    """Blank quoted corpus references, keeping every line and column exactly where it was."""
    if path != CORPUS_FILE:
        return text
    return REFERENCE_VALUE.sub(lambda match: match.group(1) + "x" * len(match.group(2)) + match.group(3), text)


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
    root = file_sets.git_root()
    if args.paths:
        # - an imported patch keeps the upstream prose it carries, so only our own text suffixes are read
        return root, [path for path in args.paths if path not in skip and file_sets.is_text(path)]
    return root, file_sets.tracked_text_files(root, skip)
