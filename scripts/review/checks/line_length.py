"""No source line over 120 characters; a line inside a string literal is accepted as a kind.

Ruff's formatter wraps code, but it cannot split a literal or a template: the repository holds long
prompts, URLs and embedded HTML/JS blocks, and those lines would be flagged forever. The rule keeps
literal and template lines as an accepted kind rather than a per-file list, using the tokenizer to
know which lines are string content and flagging what is really code or a comment.
"""

from __future__ import annotations

import argparse
import io
import tokenize

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import maintained_files

# - the one number this rule owns; ruff's formatter uses the same width
LIMIT = 120

STRING_START = ('"', "'", 'f"', "f'", 'r"', "r'", 'rf"', "rf'", 'b"', "b'")


def string_lines(text: str) -> set[int]:
    """Every line whose content belongs to a string token, including multi-line templates."""
    covered: set[int] = set()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return covered
    for token in tokens:
        if token.type == tokenize.STRING:
            covered.update(range(token.start[0], token.end[0] + 1))
    return covered


def is_literal_line(line: str) -> bool:
    """Whether this line is a long literal rather than code that could be wrapped."""
    stripped = line.strip()
    return stripped.startswith(STRING_START) or len(stripped) == 0


def findings(paths=None) -> list[tuple[str, int, int]]:
    """(path, line, length) for every line over the limit that is neither string content nor a literal."""
    found = []
    for path in maintained_files() if paths is None else paths:
        if path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        covered = string_lines(text)
        try:
            relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        except ValueError:
            # - a caller can hand in a scratch file, and the report still has to name it
            relative = path.as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            if len(line) <= LIMIT or number in covered or is_literal_line(line):
                continue
            found.append((relative, number, len(line)))
    return found


def literals(paths=None) -> int:
    """How many lines over the limit are accepted because they are string content."""
    count = 0
    for path in maintained_files() if paths is None else paths:
        if path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        covered = string_lines(text)
        for number, line in enumerate(text.splitlines(), start=1):
            if len(line) > LIMIT and (number in covered or is_literal_line(line)):
                count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    over = findings()
    for relative, number, length in over[:MAX_REPORTED]:
        print(f"[FAIL] {relative}:{number}: {length} characters; wrap it")
    if len(over) > MAX_REPORTED:
        print(f"[WARN] {len(over) - MAX_REPORTED} further lines; output bounded at {MAX_REPORTED}")
    accepted = literals()
    print(
        f"[{'FAIL' if over else 'OK'}] Line length: {len(over)} over {LIMIT} to wrap, "
        f"{accepted} string-content lines accepted"
    )
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
