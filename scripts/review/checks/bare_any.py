"""A maintained signature may not be a bare `Any`: name the real type, or `object` when it is opaque.

`dict[str, Any]` is the accepted JSON idiom and is not flagged. A parameter or return annotated exactly
`Any` switches type checking off at a boundary and lets the value flow onward unchecked, so the tests
tree is the only exemption and only because fixtures double for arbitrary doubles.
"""

from __future__ import annotations

import argparse
import ast

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import maintained_files


def bare_any(path) -> list[tuple[str, int, str]]:
    """(path, line, signature text) for every parameter or return annotated exactly `Any`."""
    found = []
    try:
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    except ValueError:
        # - a caller can hand in a scratch file, and the report still has to name it
        relative = path.as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return found
    for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]:
        arguments = [
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
            *([function.args.vararg] if function.args.vararg else []),
            *([function.args.kwarg] if function.args.kwarg else []),
        ]
        for argument in arguments:
            if isinstance(argument.annotation, ast.Name) and argument.annotation.id == "Any":
                found.append((relative, function.lineno, f"{function.name}({argument.arg}: Any)"))
        if isinstance(function.returns, ast.Name) and function.returns.id == "Any":
            found.append((relative, function.lineno, f"{function.name}() -> Any"))
    return found


def findings() -> list[tuple[str, int, str]]:
    """Every bare `Any` outside the tests tree."""
    found = []
    for path in maintained_files():
        if path.suffix != ".py":
            continue
        if path.relative_to(project_cfg.BASE_DIR).as_posix().startswith("scripts/tests/"):
            continue
        found.extend(bare_any(path))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    over = findings()
    for relative, line, signature in over[:MAX_REPORTED]:
        print(f"[FAIL] {relative}:{line}: {signature}")
    if len(over) > MAX_REPORTED:
        print(f"[WARN] {len(over) - MAX_REPORTED} further signatures; output bounded at {MAX_REPORTED}")
    print(f"[{'FAIL' if over else 'OK'}] Bare Any: {len(over)} signature(s) outside the tests tree")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
