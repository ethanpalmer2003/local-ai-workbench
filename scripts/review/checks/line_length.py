"""No source line over 120 characters; template content and token-like literals are the only exemptions.

Ruff's formatter wraps code but cannot split a literal. The rule therefore flags a line in three cases -
code that could be wrapped, a prose sentence written as one literal, and a long token that is not prose -
and exempts only the two groups where wrapping would change meaning or add noise: lines inside a multi-line
template or docstring, and single-line literals that carry no sentence (URLs, ids, encoded values).
"""

import argparse
import io
import re
import tokenize

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import maintained_files

# - the one number this rule owns; ruff's formatter uses the same width
LIMIT = 120
# - a literal with this many words is a sentence: it can be wrapped without changing a byte
PROSE_WORDS = 8
# - structure that marks a literal as data, a command or a template rather than a sentence
DATA_MARKERS = ("\\n", "://", "|", "&&", "::", "{", "}", "<", ">", "=", "$", "\\", ";")


def string_spans(text: str) -> list[tuple[int, int, str]]:
    """(first line, last line, literal text) for every string token, including multi-line templates.

    Python 3.12 and later tokenize an f-string as FSTRING_START, FSTRING_MIDDLE and FSTRING_END, so the
    three are stitched back into one span; the middle parts are the literal text a rule can read.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    spans: list[tuple[int, int, str]] = []
    start: tuple[int, int] | None = None
    middle: list[str] = []
    for token in tokens:
        name = tokenize.tok_name.get(token.type, "")
        if name == "FSTRING_START":
            start, middle = token.start, []
        elif name == "FSTRING_MIDDLE":
            middle.append(token.string)
        elif name == "FSTRING_END" and start is not None:
            spans.append((start[0], token.end[0], "".join(middle)))
            start = None
        elif token.type == tokenize.STRING:
            spans.append((token.start[0], token.end[0], token.string))
    return spans


def sentence_like(literal: str) -> bool:
    """Whether a literal reads as prose: enough words and none of the structure that marks data."""
    body = literal.strip().strip("\"'").strip()
    if any(marker in body for marker in DATA_MARKERS):
        return False
    return len(re.findall(r"[A-Za-z]{3,}", body)) >= PROSE_WORDS


def classify(line: str, number: int, spans: list[tuple[int, int, str]]) -> str:
    """`code`, `prose`, `token` or `template` for one line: what a long line actually holds."""
    covering = [span for span in spans if span[0] <= number <= span[1]]
    if any(last > first for first, last, _ in covering):
        return "template"
    if covering:
        return "prose" if any(sentence_like(literal) for _, _, literal in covering) else "token"
    return "code"


def audit(paths=None) -> list[tuple[str, int, int, str]]:
    """(path, line, length, kind) for every line over the limit."""
    found = []
    for path in maintained_files() if paths is None else paths:
        if path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        spans = string_spans(text)
        try:
            relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        except ValueError:
            # - a caller can hand in a scratch file, and the report still has to name it
            relative = path.as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            if len(line) <= LIMIT:
                continue
            found.append((relative, number, len(line), classify(line, number, spans)))
    return found


def findings(paths=None) -> list[tuple[str, int, int, str]]:
    """Long lines that a reader should fix: code and prose, not templates or long tokens."""
    return [item for item in audit(paths) if item[3] in {"code", "prose"}]


def accepted(paths=None) -> dict[str, int]:
    """How many long lines are accepted, by kind."""
    counts = {"template": 0, "token": 0}
    for item in audit(paths):
        if item[3] in counts:
            counts[item[3]] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    over = findings()
    for relative, number, length, kind in over[:MAX_REPORTED]:
        print(f"[FAIL] {relative}:{number}: {length} characters ({kind}); wrap it")
    if len(over) > MAX_REPORTED:
        print(f"[WARN] {len(over) - MAX_REPORTED} further lines; output bounded at {MAX_REPORTED}")
    accepted_counts = accepted()
    print(
        f"[{'FAIL' if over else 'OK'}] Line length: {len(over)} over {LIMIT} to wrap, "
        f"{accepted_counts['template']} template and {accepted_counts['token']} token lines accepted"
    )
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
