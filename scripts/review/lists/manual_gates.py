"""Live inventory of the manual-run guard: every place that references it, computed from source.

A written list of these call sites would rot on the first refactor, so nothing else names them;
ask this module instead. Kinds are guard (calls consent.manual_refused), definition (consent.py
itself), passthrough (hands --manual onward), test, and documented (.md mentions).
"""

import ast
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.file_sets import maintained_files
from scripts.shared.tables import render_table

GUARD_CALL = "manual_refused"
MANUAL_FLAG = "--manual"
CONSENT_MODULE = "scripts/shared/consent.py"
# - the runner, registry and validate live under scripts/tests/ too, so only cases/ counts as tests
TEST_CASES_DIR = "scripts/tests/cases/"


@dataclass(frozen=True)
class Usage:
    file: str
    line: int
    kind: str


def _calls_guard(node: ast.Call) -> bool:
    """Whether this call invokes consent.manual_refused, directly or through the module."""
    func = node.func
    return (isinstance(func, ast.Name) and func.id == GUARD_CALL) or (
        isinstance(func, ast.Attribute) and func.attr == GUARD_CALL
    )


def _docstring_lines(tree: ast.AST) -> set[int]:
    """Line numbers covered by docstrings, which mention names without using them."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        body = (
            node.body if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
        )
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            lines.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    return lines


def _python_usages(path: Path, relative: str) -> list[Usage]:
    """Guard calls and --manual literals in one Python file, with their line numbers."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    prose = _docstring_lines(tree)
    found: list[Usage] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _calls_guard(node):
            found.append(Usage(relative, node.lineno, "test" if relative.startswith(TEST_CASES_DIR) else "guard"))
        elif isinstance(node, ast.Constant) and node.value == MANUAL_FLAG and node.lineno not in prose:
            if relative == CONSENT_MODULE:
                kind = "definition"
            elif relative.startswith(TEST_CASES_DIR):
                kind = "test"
            else:
                kind = "passthrough"
            found.append(Usage(relative, node.lineno, kind))
    return found


def _text_usages(path: Path, relative: str, kind: str) -> list[Usage]:
    """--manual mentions in one batch file or document, with their line numbers."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [Usage(relative, number, kind) for number, line in enumerate(lines, 1) if MANUAL_FLAG in line]


def usages(paths: list[Path] | None = None) -> list[Usage]:
    """Every live reference to the manual-run guard, sorted by file and line."""
    if paths is None:
        paths = [path for path in maintained_files() if path.suffix in (".py", ".bat", ".md")]
    found: list[Usage] = []
    for path in paths:
        try:
            relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        except ValueError:
            continue
        if path.suffix == ".py":
            found.extend(_python_usages(path, relative))
        elif path.suffix == ".bat":
            found.extend(_text_usages(path, relative, "passthrough"))
        else:
            found.extend(_text_usages(path, relative, "documented"))
    return sorted(found, key=lambda use: (use.file, use.line))


def report() -> str:
    """The inventory as an aligned table, for the console or an answer."""
    return render_table([[use.file, str(use.line), use.kind] for use in usages()], ["file", "line", "kind"])


def main() -> int:
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
