"""Console output is one line or a table: a print may not emit two content lines.

`print("a\\nb")` makes the number of console lines a property of prose rather than data, and the
reader cannot tell how long a run will be. Reports belong in `scripts/shared/tables.render_table`,
which builds every row from the data; a leading blank line before a heading stays allowed, because it
is a separator rather than a second line of output.

`--census` counts every print by the number of content lines it can emit, which is how a decision to
widen or narrow the rule starts.
"""

import argparse
import ast
from collections import Counter
from pathlib import Path

from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import check_targets
from scripts.shared.paths import display_path


def _literal_lines(values: list[str]) -> int:
    """Content lines the joined literals emit; a leading or trailing blank line is a separator."""
    text = "".join(values)
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return len(lines)


def _print_strings(node: ast.Call) -> list[str]:
    """Every literal string a print call contributes, from plain strings and f-strings alike."""
    found: list[str] = []
    for argument in node.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            found.append(argument.value)
        elif isinstance(argument, ast.JoinedStr):
            found.extend(
                value.value
                for value in argument.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
    return found


def _sites(tree: ast.Module) -> list[tuple[ast.Call, int]]:
    """Every print call with the number of content lines its literals can emit."""
    sites: list[tuple[ast.Call, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            sites.append((node, _literal_lines(_print_strings(node))))
    return sites


def _tree(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return None


def issues(path: Path) -> list[str]:
    """Every print in one file that would emit more than one line of content."""
    tree = _tree(path)
    if tree is None:
        return []
    return [
        f"{display_path(path)}:{node.lineno}: print emits {lines} lines; use render_table"
        for node, lines in _sites(tree)
        if lines > 1
    ]


def census(paths: list[Path]) -> Counter[int]:
    """How many prints emit each number of content lines."""
    counts: Counter[int] = Counter()
    for path in paths:
        tree = _tree(path)
        if tree is not None:
            counts.update(lines for _node, lines in _sites(tree))
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check (default: every maintained Python file)")
    parser.add_argument("--census", action="store_true", help="count prints by content lines instead of checking")
    args = parser.parse_args(argv)
    files = check_targets(args.paths, (".py",))
    if args.census:
        counts = census(files)
        for lines, count in sorted(counts.items()):
            print(f"[COUNT] {count:5d}  {lines} line(s)")
        print(f"[OK] Output: {sum(counts.values())} print call(s) in {len(files)} files")
        return 0
    found = [issue for path in files for issue in issues(path)]
    if not found:
        print(f"[OK] Output: {len(files)} files, every print is one line or a table")
        return 0
    for issue in found[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    print(f"[FAIL] Output: {len(found)} multi-line print(s) in {len(files)} files")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
