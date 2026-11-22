"""A condition nests operators to three levels: its root, at most two inside it.

`a or (b and (c or (d and e)))` reads as one sentence with a hinge a reader has to hold in working
memory, and the fix is the same every time: extract `blocked = b and c` and the condition becomes a
short list of named facts. A chain inside one operator node (`a or b or c`) stays allowed, because it
is read in one pass; what the check counts is how deep operator nodes nest. A call or comprehension is
one fact whatever it contains, so its inside is not counted.
"""

import ast

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import check_targets

# - the first nesting depth the rule refuses: root plus two inside it is the allowance
MAX_DEPTH = 3
CONDITIONS = ast.If | ast.While | ast.IfExp
# - a call or comprehension is one fact whatever it does inside; the rule is about the condition's own hooks
OPAQUE = ast.Call | ast.Lambda | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp


def nesting(node: ast.expr, depth: int = 0) -> int:
    """How deeply boolean, comparison and negation operators nest inside one condition."""
    deepest = depth
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, ast.expr) or isinstance(child, OPAQUE):
            continue
        inner = depth + 1 if isinstance(child, (ast.BoolOp, ast.Compare, ast.UnaryOp)) else depth
        deepest = max(deepest, nesting(child, inner))
    return deepest


def overlong_conditions(path) -> list[tuple[str, int, int, str]]:
    """(path, line, depth, source) for every if/while/ternary whose condition nests too deeply."""
    found: list[tuple[str, int, int, str]] = []
    try:
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    except ValueError:
        relative = path.as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, CONDITIONS) or node.test is None:
            continue
        depth = nesting(node.test)
        if depth >= MAX_DEPTH:
            found.append((relative, getattr(node, "lineno", 0), depth, ast.unparse(node.test)))
    return found


def main(paths: list[str] | None = None) -> int:
    """Report every condition above the nesting limit; exit 1 when one is found."""
    targets = check_targets(paths, (".py",)) if paths else check_targets(None, (".py",))
    findings = [item for path in targets for item in overlong_conditions(path)]
    for relative, line, depth, source in findings[:MAX_REPORTED]:
        print(f"{relative}:{line}: condition nests {depth} operator layer(s): {source}")
    if len(findings) > MAX_REPORTED:
        print(f"[TRUNCATED] {len(findings) - MAX_REPORTED} more finding(s)")
    if findings:
        print(f"[FAIL] {len(findings)} condition(s) nest {MAX_DEPTH} or more operator layers; name the parts")
        return 1
    print(f"[OK] Expression depth: {len(targets)} files, every condition nests fewer than {MAX_DEPTH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
