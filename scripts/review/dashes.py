"""Reject em-dashes and en-dashes in text that ships, so pushed files stay plain ASCII punctuation.

- Em-dashes and en-dashes are typographic substitutes; a hyphen between spaces says the same
- The pinned corpus quotes third-party transcript text verbatim, so its reference values are
  masked before scanning: the quoted sentences are data, not our prose
"""

import argparse
import re
import subprocess
from pathlib import Path

DASHES = re.compile(r"[\u2014\u2013]")
# - escaped characters stay inside the value, so the mask keeps the exact width of what it hides
REFERENCE_VALUE = re.compile(r'("reference"\s*:\s*")([^"\\]*(?:\\.[^"\\]*)*)(")')
REFERENCE_FILE = "scripts/config/benchmarks/language_corpus.json"
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".bat",
    ".cjs",
    ".js",
    ".ts",
    ".ini",
    ".kcpps",
    ".txt",
    ".jinja",
    ".toml",
    ".ps1",
    ".cfg",
    ".csv",
    ".html",
    ".css",
}


def masked(text: str, path: str) -> str:
    """The text with quoted corpus references blanked, keeping line and column numbering exact."""
    if path != REFERENCE_FILE:
        return text
    return REFERENCE_VALUE.sub(lambda match: match.group(1) + "x" * len(match.group(2)) + match.group(3), text)


def scan_text(path: str, text: str) -> list[tuple[int, str]]:
    """Line and dash kind for every typographic dash this file would publish."""
    findings = []
    for number, line in enumerate(masked(text, path).splitlines(), 1):
        for match in DASHES.finditer(line):
            findings.append((number, "em-dash" if match.group(0) == "\u2014" else "en-dash"))
    return findings


def is_text(path: str) -> bool:
    """Whether this path is text we write; generated evidence is ignored by git, not by suffix."""
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def tracked_text_files(root: Path) -> list[str]:
    """Every tracked file whose content is text we write."""
    result = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True)
    return [path for path in result.stdout.splitlines() if path and is_text(path)]


def check(root: Path, paths: list[str]) -> int:
    findings = [
        (path, number, kind)
        for path in paths
        for number, kind in scan_text(path, (root / path).read_text(encoding="utf-8", errors="ignore"))
    ]
    for path, number, kind in findings:
        print(f"[FAIL] {path}:{number}: {kind}")
    print(f"{len(findings)} typographic dash(es); plain hyphens and commas are fine")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check (default: every tracked text file)")
    args = parser.parse_args(argv)
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    paths = args.paths or tracked_text_files(root)
    return check(root, paths)


if __name__ == "__main__":
    raise SystemExit(main())
