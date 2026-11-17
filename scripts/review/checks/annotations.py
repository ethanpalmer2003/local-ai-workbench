"""Annotation complexity: a nested tuple in a signature hides the record it actually means.

`dict[int, list[tuple[int, str, bool, set[tuple[str, int]], bool]]]` says five things at once and names
none of them; a dataclass or `NamedTuple` says the same and reads. No maintained tool checks this -
ruff, basedpyright, pylint and vulture all stop at whether a type exists, not at whether it is legible -
so the score is spelled out here: one point per atom, two per level of nesting, two per union member.
Between `WARN_SCORE` and `MAX_SCORE` the finding is a prompt; above `MAX_SCORE` it fails the gate.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import maintained_files

# - the two ends of one rule: the worst annotation in this tree scores 20, and 22 sit above 14
WARN_SCORE = 14
MAX_SCORE = 16
# - a chain deeper than three subscripts fails on its own, the one signal the flat score can dilute
MAX_DEPTH = 3


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    over = findings()
    for item in over[:MAX_REPORTED]:
        print(f"[{'FAIL' if item.score > MAX_SCORE or item.depth > MAX_DEPTH else 'INFO'}] {item}")
    if len(over) > MAX_REPORTED:
        print(f"[WARN] {len(over) - MAX_REPORTED} further annotations; output bounded at {MAX_REPORTED}")
    failed = [item for item in over if item.score > MAX_SCORE or item.depth > MAX_DEPTH]
    print(
        f"[{'FAIL' if failed else 'OK'}] Annotations: {len(over)} under watch, "
        f"{len(failed)} over the cap (score above {MAX_SCORE} or depth above {MAX_DEPTH})"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
