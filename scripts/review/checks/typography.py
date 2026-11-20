"""Reject typographic substitutes in text that ships, so every pushed file stays plain ASCII punctuation.

- Dashes, curly quotes, the ellipsis and no-break spaces are what editors and chat interfaces
  insert by default; they read as prose flourishes and survive copy-paste into code
- The same flourish in ASCII is a spaced dash between two words, so a Python docstring or comment
  is refused for it as well; a list bullet and the `# -` comment marker put the dash at the start
- A control character is an escape a shell expanded on the way in: BEL stands where an `a` was, VT
  where a `v` was, a tab where a `t` was. The line endings and an indent tab stay legal, and a
  patch keeps whatever the upstream file already contained
- The pinned corpus quotes third-party transcript text verbatim, so its reference values are
  masked before scanning: the quoted sentences are data, not our prose
"""

import argparse
import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

from scripts.review.lists.text_files import tracked_text_files

# - character -> readable kind; every one has a plain ASCII replacement
BANNED = {
    "\u2014": "em-dash",
    "\u2013": "en-dash",
    "\u2012": "figure-dash",
    "\u2212": "minus-sign",
    "\u2018": "left-single-quote",
    "\u2019": "right-single-quote",
    "\u201c": "left-double-quote",
    "\u201d": "right-double-quote",
    "\u2026": "ellipsis",
    "\u00a0": "no-break-space",
    "\u202f": "narrow-no-break-space",
    "\u00ad": "soft-hyphen",
}
# - every control character except tab, line feed and carriage return; a generic escape corrupts a word
CONTROL = {
    **{chr(code): f"control-character U+{code:04X}" for code in range(0x00, 0x09)},
    "\u000b": "control-character U+000B",
    "\u000c": "control-character U+000C",
    **{chr(code): f"control-character U+{code:04X}" for code in range(0x0E, 0x20)},
    "\u007f": "control-character U+007F",
}
SUSPECT = BANNED | CONTROL
SUSPECT_PATTERN = re.compile("|".join(re.escape(character) for character in SUSPECT))
# - escaped characters stay inside the value, so the mask keeps the exact width of what it hides
REFERENCE_VALUE = re.compile(r'("reference"\s*:\s*")([^"\\]*(?:\\.[^"\\]*)*)(")')
REFERENCE_FILE = "scripts/config/benchmarks/language_corpus.json"


def masked(text: str, path: str) -> str:
    """The text with quoted corpus references blanked, keeping line and column numbering exact."""
    if path != REFERENCE_FILE:
        return text
    return REFERENCE_VALUE.sub(lambda match: match.group(1) + "x" * len(match.group(2)) + match.group(3), text)


def scan_text(path: str, text: str) -> list[tuple[int, str]]:
    """Line and kind for every substitute or control character this file would publish.

    The text splits on the line feed alone: `splitlines` also breaks on a vertical tab and a form
    feed, which is how a corrupted word would vanish from the scan instead of being reported.
    """
    findings = []
    for number, line in enumerate(masked(text, path).split("\n"), 1):
        findings.extend((number, SUSPECT[match.group(0)]) for match in SUSPECT_PATTERN.finditer(line))
    return findings


WORD_DASH = re.compile(r"(?<=[A-Za-z0-9]) - (?=[A-Za-z0-9])")
DOCSTRING_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def prose_dashes(path: str, text: str) -> list[tuple[int, str]]:
    """Line and kind for every spaced dash between words inside a Python docstring or comment.

    A bullet in a docstring and the `# -` comment marker start with the dash, so they stay legal.
    A dash joining two words is the prose habit this refuses, in ASCII form. A file that does not
    parse is left to the lint and type sections, which report it themselves.
    """
    if not path.endswith(".py"):
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, DOCSTRING_NODES):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if not docstring:
            continue
        for offset, line in enumerate(docstring.splitlines()):
            if WORD_DASH.search(line):
                findings.append((node.body[0].lineno + offset, "prose-dash"))
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError):
        return findings
    findings.extend(
        (token.start[0], "prose-dash")
        for token in tokens
        if token.type == tokenize.COMMENT and WORD_DASH.search(token.string)
    )
    return findings


def check(root: Path, paths: list[str]) -> int:
    findings = []
    for path in paths:
        text = (root / path).read_text(encoding="utf-8", errors="ignore")
        findings.extend((path, number, kind) for number, kind in scan_text(path, text))
        findings.extend((path, number, kind) for number, kind in prose_dashes(path, text))
    for path, number, kind in findings:
        print(f"[FAIL] {path}:{number}: {kind}")
    print(f"{len(findings)} unpublishable character(s); straight quotes, three dots and single spaces are fine")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check (default: every tracked text file)")
    args = parser.parse_args(argv)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    root = Path(top.stdout.strip())
    return check(root, args.paths or tracked_text_files(root))


if __name__ == "__main__":
    raise SystemExit(main())
