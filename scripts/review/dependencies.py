"""Report installed packages the repository never imports, from the real import graph."""

import ast
import re
from importlib.metadata import distributions, packages_distributions
from pathlib import Path
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import Requirement

from scripts.config import project_config as project_cfg

SKIP_DIRS = {".venv", "state", "output", "trash", "frameworks", "data", "__pycache__", "old", "retired"}
# - tools the workflow runs but no module imports
TOOL_ROOTS = {
    "pytest",
    "ruff",
    "basedpyright",
    "codespell",
    "pip-audit",
    "coverage",
    "pre-commit",
    "virtualenv",
    "pip",
    "setuptools",
    "wheel",
}


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _import_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def project_imports(root: Path | None = None) -> set[str]:
    """Top-level module names imported by maintained project code."""
    root = project_cfg.SCRIPTS_DIR if root is None else root
    modules: set[str] = set()
    for path in root.rglob("*.py"):
        if SKIP_DIRS & set(path.parts):
            continue
        try:
            modules.update(_import_names(ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))))
        except SyntaxError:
            continue
    return modules


def installed() -> dict[str, str]:
    """Normalized name -> version for every installed distribution."""
    return {_normalized(dist.metadata["Name"]): dist.version for dist in distributions() if dist.metadata["Name"]}


def _declared() -> dict[str, list[str]]:
    declared: dict[str, list[str]] = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        if name:
            declared[_normalized(name)] = list(dist.requires or [])
    return declared


def _requirement(text: str) -> Requirement | None:
    try:
        return Requirement(text)
    except Exception:
        return None


def _dependencies(declared: dict[str, list[str]], name: str) -> list[str]:
    environment: dict[str, Any] = {**default_environment(), "extra": ""}
    names = []
    for text in declared.get(name, []):
        parsed = _requirement(text)
        if parsed is None or (parsed.marker is not None and not parsed.marker.evaluate(environment=environment)):
            continue
        names.append(_normalized(parsed.name))
    return names


def required_names() -> set[str]:
    """Everything the imports and tool roots reach, transitively."""
    declared = _declared()
    known = installed()
    mapping = packages_distributions()
    roots = {dist for module in project_imports() for dist in mapping.get(module, [])} | TOOL_ROOTS
    reached: set[str] = set()
    pending = [_normalized(name) for name in roots]
    while pending:
        name = pending.pop()
        if name in reached or name not in known:
            continue
        reached.add(name)
        pending.extend(_dependencies(declared, name))
    return reached


def unused_packages() -> list[tuple[str, str]]:
    """(display name, version) for installed distributions nothing requires."""
    known = installed()
    display = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        if name:
            display[_normalized(name)] = name
    reachable = required_names()
    return sorted(((display[name], known[name]) for name in set(known) - reachable), key=lambda row: row[0].casefold())


def main() -> int:
    unused = unused_packages()
    print(f"{len(unused)} installed package(s) are outside the import graph")
    for name, version in unused:
        print(f"  {name} {version}")
    if unused:
        print("\nRemove with:\n  uv pip uninstall " + " ".join(name for name, _ in unused))
    return 0
