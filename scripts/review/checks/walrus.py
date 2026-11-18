"""One assignment per statement: a walrus inside a comprehension hides where the value comes from.

`[item for item in items if (found := look(item))]` reads as a filter and also binds `found` on every
pass, so a reader has to unroll the comprehension to see what is stored and when. A `while chunk :=
read()` header stays allowed: there the assignment is the whole point of the line.

`--census` counts the shapes the rule still permits, which is how a decision to widen it starts.
"""

import argparse
import ast
from collections import Counter
from pathlib import Path

from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import check_targets
from scripts.shared.paths import display_path

COMPREHENSIONS = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
BANNED = "inside a comprehension"


def _context(node: ast.NamedExpr, parents: dict[ast.AST, ast.AST]) -> str:
    """Where a walrus sits, named by the first statement that contains it."""
    current: ast.AST = node
    while current in parents:
        current = parents[current]
        if isinstance(current, COMPREHENSIONS):
            return BANNED
        if isinstance(current, ast.While):
            return "while header"
        if isinstance(current, ast.If):
            return "if header"
    return "inside a statement"


def _tree(path: Path) -> ast.Module | None:
    """The parsed file, or None when it cannot be read or parsed."""
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return None


def _sites(tree: ast.Module) -> list[tuple[ast.NamedExpr, str]]:
    """Every walrus in one tree, each with the shape of the statement around it."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    return [(node, _context(node, parents)) for node in ast.walk(tree) if isinstance(node, ast.NamedExpr)]


def issues(path: Path) -> list[str]:
    """Every walrus bound inside a comprehension in one file, with the name it binds."""
    tree = _tree(path)
    if tree is None:
        return []
    return [
        f"{display_path(path)}:{node.lineno}: walrus {BANNED} ({node.target.id})"
        for node, kind in _sites(tree)
        if kind == BANNED and isinstance(node.target, ast.Name)
    ]


def contexts(paths: list[Path]) -> Counter[str]:
    """How many walrus operators sit in each shape, so a census can price widening the rule."""
    census: Counter[str] = Counter()
    for path in paths:
        tree = _tree(path)
        if tree is not None:
            census.update(kind for _node, kind in _sites(tree))
    return census


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check (default: every maintained Python file)")
    parser.add_argument("--census", action="store_true", help="count walruses by shape instead of checking")
    args = parser.parse_args(argv)
    files = check_targets(args.paths, (".py",))
    if args.census:
        counts = contexts(files)
        for kind, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            print(f"[COUNT] {count:5d}  {kind}")
        print(f"[OK] Walrus: {sum(counts.values())} in {len(counts)} shapes")
        return 0
    found = [issue for path in files for issue in issues(path)]
    if not found:
        print(f"[OK] Walrus: {len(files)} files, 0 assign-and-test inside a comprehension")
        return 0
    for issue in found[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    print(f"[FAIL] Walrus: {len(found)} assign-and-test inside a comprehension in {len(files)} files")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
