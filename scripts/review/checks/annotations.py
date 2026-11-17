"""Signature shape: a nested tuple hides the record it means, and a computed default hides what it holds.

`dict[int, list[tuple[int, str, bool, set[tuple[str, int]], bool]]]` says five things at once and names
none of them; a dataclass or `NamedTuple` says the same and reads. No maintained tool checks that -
ruff, basedpyright, pylint and vulture all stop at whether a type exists, not at whether it is legible -
so the score is spelled out here: one point per atom, two per level of nesting, two per union member.
Between `WARN_SCORE` and `MAX_SCORE` the finding is a prompt; above `MAX_SCORE` it fails the gate.

The second rule is about the default beside the annotation. A default may be a literal, a tuple of
literals, `None`, or an empty `frozenset`; it may not be a mutable container, a call, or a read of a
settings object, because every one of those is evaluated once when the module is imported. Pass `None`
and resolve it in the body instead, where a test can replace it.
"""

import argparse
import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import check_targets, maintained_files

# - the two ends of one rule: the worst annotation in this tree scores 20, and 22 sit above 14
WARN_SCORE = 14
MAX_SCORE = 16
# - a chain deeper than three subscripts fails on its own, the one signal the flat score can dilute
MAX_DEPTH = 3
# - config modules here are imported by name and read as attributes, so a default naming one freezes it
CONFIG_MODULES = frozenset({"cfg", "project_cfg", "project_config", "launcher_config"})
IMMUTABLE_CALLS = frozenset({"frozenset"})
MUTABLE_CALLS = frozenset({"list", "dict", "set", "defaultdict", "OrderedDict"})


@dataclass(frozen=True)
class Annotation:
    """One parameter or return type with its score and the pieces that produced it."""

    path: str
    function: str
    line: int
    score: int
    pieces: int
    depth: int
    union: int

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.function} scores {self.score} "
            f"({self.pieces} atoms, depth {self.depth}, {self.union} union members)"
        )


def score(node: ast.AST | None) -> tuple[int, int, int]:
    """(atoms, nesting depth, widest union) for one annotation."""
    if node is None:
        return 0, 0, 0
    if isinstance(node, ast.Subscript):
        value = score(node.value)
        inner = score(node.slice)
        return value[0] + inner[0], max(value[1], inner[1]) + 1, max(value[2], inner[2])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = score(node.left)
        right = score(node.right)
        return left[0] + right[0], max(left[1], right[1]), max(left[2], right[2], _union_members(node))
    if isinstance(node, ast.Tuple):
        parts = [score(element) for element in node.elts]
        return (
            sum(part[0] for part in parts),
            max((part[1] for part in parts), default=0),
            max((part[2] for part in parts), default=0),
        )
    if isinstance(node, ast.Name | ast.Attribute | ast.Constant):
        return 1, 0, 0
    return sum(score(child)[0] for child in ast.iter_child_nodes(node)), 0, 0


def _union_members(node: ast.BinOp) -> int:
    """How many types one `|` chain names."""
    count = 0
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.BinOp) and isinstance(current.op, ast.BitOr):
            stack.extend((current.left, current.right))
        else:
            count += 1
    return count


def annotation_score(node: ast.AST | None) -> Annotation | None:
    """The record for one annotation, or None when it carries none."""
    if node is None:
        return None
    pieces, depth, union = score(node)
    return Annotation("", "", 0, pieces + 2 * depth + 2 * union, pieces, depth, union)


def annotations_in(path: Path) -> Iterable[Annotation]:
    """Every parameter and return annotation in one file, scored."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return
    try:
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    except ValueError:
        # - a caller can hand in a scratch file, and the report still has to name it
        relative = path.as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        declared = [argument.annotation for argument in (*node.args.posonlyargs, *node.args.args)]
        declared += [argument.annotation for argument in node.args.kwonlyargs]
        declared.append(node.returns)
        for annotation in declared:
            scored = annotation_score(annotation)
            if scored is None:
                continue
            yield Annotation(relative, node.name, node.lineno, scored.score, scored.pieces, scored.depth, scored.union)


def findings(paths: list[Path] | None = None) -> list[Annotation]:
    """Annotations at or above the warning score, worst first, one row per function and score."""
    sources = [path for path in (maintained_files() if paths is None else paths) if path.suffix == ".py"]
    scored = [
        item for path in sources for item in annotations_in(path) if item.score >= WARN_SCORE or item.depth > MAX_DEPTH
    ]
    # - one function with four heavy parameters is one thing to fix, not four findings
    unique: dict[tuple[str, str, int], Annotation] = {}
    for item in scored:
        unique.setdefault((item.path, item.function, item.score), item)
    return sorted(unique.values(), key=lambda item: (-item.score, item.path, item.line))


def future_imports(paths: list[Path] | None = None) -> list[Path]:
    """Files that switch annotations to strings; the interpreters here already defer them.

    The statement is read as syntax, not as text, so this module and its test can name it.
    """
    sources = [path for path in (maintained_files() if paths is None else paths) if path.suffix == ".py"]
    stale = []
    for path in sources:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):
            continue
        imports_future = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in tree.body
        )
        if imports_future:
            stale.append(path)
    return stale


def _config_read(node: ast.expr) -> str | None:
    """A bare `cfg.VALUE` is frozen at import; `cfg.Kind.MEMBER` names a class constant and is fine."""
    depth = 0
    root = node
    while isinstance(root, ast.Attribute):
        depth += 1
        root = root.value
    if isinstance(root, ast.Name) and root.id in CONFIG_MODULES and depth < 2:
        return f"reads {ast.unparse(node)}"
    return None


def _default_problem(node: ast.expr) -> str | None:
    """Why a default cannot be evaluated once at import, or None when it can."""
    if isinstance(node, ast.Constant | ast.Name | ast.Lambda | ast.BinOp):
        return None
    # - a lookup in a module-level table is a constant, like the name beside it
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return None
    if isinstance(node, ast.Tuple):
        return next((problem for item in node.elts if (problem := _default_problem(item))), None)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in IMMUTABLE_CALLS and not node.args and not node.keywords:
            return None
        return f"calls {node.func.id}()"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return f"calls {ast.unparse(node.func)}()"
    if isinstance(node, ast.Attribute):
        return _config_read(node)
    return f"evaluates {ast.unparse(node)}"


def default_findings(paths: list[Path] | None = None) -> list[tuple[str, int, str]]:
    """Repo-relative path, line and reason for every default that is computed when the module loads."""
    sources = [path for path in (maintained_files() if paths is None else paths) if path.suffix == ".py"]
    found = []
    for path in sources:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            args = node.args
            positional = args.args[len(args.args) - len(args.defaults) :] if args.defaults else []
            for argument, default in zip(
                [*positional, *args.kwonlyargs], [*args.defaults, *args.kw_defaults], strict=False
            ):
                if default is None:
                    continue
                if isinstance(default, ast.List | ast.Dict | ast.Set) or (
                    isinstance(default, ast.Call)
                    and isinstance(default.func, ast.Name)
                    and default.func.id in MUTABLE_CALLS
                ):
                    found.append((relative, default.lineno, f"{node.name}({argument.arg}) is a mutable default"))
                    continue
                if problem := _default_problem(default):
                    found.append((relative, default.lineno, f"{node.name}({argument.arg}) default {problem}"))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check (default: every maintained Python file)")
    args = parser.parse_args(argv)
    targets = check_targets(args.paths, (".py",))
    over = findings(targets)
    for item in over[:MAX_REPORTED]:
        print(f"[{'FAIL' if item.score > MAX_SCORE or item.depth > MAX_DEPTH else 'INFO'}] {item}")
    if len(over) > MAX_REPORTED:
        print(f"[WARN] {len(over) - MAX_REPORTED} further annotations; output bounded at {MAX_REPORTED}")
    stale = future_imports(targets)
    for path in stale[:MAX_REPORTED]:
        print(f"[FAIL] {path.relative_to(project_cfg.BASE_DIR).as_posix()}: drop the future import")
    defaults = default_findings(targets)
    for path, line, reason in defaults[:MAX_REPORTED]:
        print(f"[FAIL] {path}:{line}: {reason}; pass None and resolve it in the body")
    failed = [item for item in over if item.score > MAX_SCORE or item.depth > MAX_DEPTH]
    print(
        f"[{'FAIL' if failed or stale or defaults else 'OK'}] Annotations: {len(over)} under watch, "
        f"{len(failed)} over the cap (score above {MAX_SCORE} or depth above {MAX_DEPTH}), "
        f"{len(stale)} with the future import, {len(defaults)} computed default(s)"
    )
    return 1 if failed or stale or defaults else 0


if __name__ == "__main__":
    raise SystemExit(main())
