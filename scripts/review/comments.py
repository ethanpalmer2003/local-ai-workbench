"""Comment policy: no TODO markers, no banner rules, no commented-out code.

Comments that explain why stay welcome; this check only rejects the three shapes that turn
comments into clutter: markers nobody owns, separator-only banners, and code kept alive only
in a comment.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

from scripts.review import MAX_REPORTED
from scripts.review.sources import maintained_files

MARKER = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
SEPARATOR = re.compile(r"^#\s*([=*#_-])\1{7,}\s*$")
CODE_NODES = (
    ast.Assign,
    ast.AnnAssign,
    ast.Call,
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Return,
    ast.If,
    ast.For,
    ast.While,
    ast.With,
    ast.Try,
)


def _marker(body: str) -> bool:
    """A marker comment; a reference to the TODO document is not one."""
    return bool(MARKER.search(body)) and "TODO.md" not in body and "notes/TODO" not in body


def _commented_out(body: str) -> bool:
    if not body or body.startswith(("-", "NOTE", "Note")):
        return False
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False
    return any(isinstance(node, CODE_NODES) for node in ast.walk(tree))


def issues(path: Path) -> list[str]:
    """Policy breaches in one file, as printable lines."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    found = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            raw = token.string
            body = raw.lstrip("#").strip()
            if _marker(body):
                found.append(f"{path.name}:{token.start[0]}: marker comment ({body[:40]})")
            elif SEPARATOR.match(raw):
                found.append(f"{path.name}:{token.start[0]}: banner rule; use one '# --- title ---' line")
            elif _commented_out(body):
                found.append(f"{path.name}:{token.start[0]}: commented-out code ({body[:40]})")
    except (tokenize.TokenError, IndentationError):
        return found
    return found


def main(argv: list[str] | None = None) -> int:
    _ = argv
    files = [path for path in maintained_files() if path.suffix == ".py"]
    found = [issue for path in files for issue in issues(path)]
    if not found:
        print(f"[OK] Comments: {len(files)} files, 0 issues")
        return 0
    for issue in found[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    print(f"[FAIL] Comments: {len(found)} issue(s) in {len(files)} files")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
