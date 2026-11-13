"""Installed distributions that are neither imported nor declared, plus uv lock consistency.

deptry owns the declared side: whether every import is covered and every declaration is used. This
module owns the leftovers, packages a past install left behind, and delegates the lock to uv.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
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
    "deptry",
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


def _python_files(root: Path) -> Iterator[Path]:
    """Project sources only; a pruned walk keeps the huge generated folders from being descended."""
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = [name for name in subfolders if name not in SKIP_DIRS]
        yield from (Path(folder) / name for name in files if name.endswith(".py"))


def project_imports(root: Path | None = None) -> set[str]:
    """Top-level module names imported by maintained project code."""
    root = project_cfg.SCRIPTS_DIR if root is None else root
    modules: set[str] = set()
    for path in _python_files(root):
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


def declared() -> set[str]:
    """Distribution names pyproject declares; deptry owns whether each one is used."""
    payload = tomllib.loads((project_cfg.BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    groups = [payload.get("project", {}).get("dependencies", [])]
    groups.extend(payload.get("dependency-groups", {}).values())
    groups.extend(payload.get("project", {}).get("optional-dependencies", {}).values())
    names: set[str] = set()
    for group in groups:
        for text in group:
            parsed = _requirement(text)
            if parsed is not None:
                names.add(_normalized(parsed.name))
    return names


def leftovers() -> list[tuple[str, str]]:
    """(display name, version) for installed distributions nothing imports and no manifest declares."""
    known = installed()
    display = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        if name:
            display[_normalized(name)] = name
    reachable = required_names() | declared()
    return sorted(((display[name], known[name]) for name in set(known) - reachable), key=lambda row: row[0].casefold())


def locked() -> dict[str, str]:
    """Normalized name -> version for every package uv.lock resolves."""
    lock = project_cfg.BASE_DIR / "uv.lock"
    if not lock.is_file():
        return {}
    payload = tomllib.loads(lock.read_text(encoding="utf-8"))
    return {
        _normalized(entry["name"]): entry["version"]
        for entry in payload.get("package", [])
        if isinstance(entry, dict) and "name" in entry and "version" in entry
    }


def lock_issues() -> list[str]:
    """uv.lock must exist and agree with pyproject; uv is the only supported installer."""
    uv = shutil.which("uv")
    if uv is None:
        return ["uv is not on PATH; the lockfile cannot be verified"]
    result = subprocess.run(
        [uv, "lock", "--check", "--offline"], cwd=project_cfg.BASE_DIR, capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        return []
    detail = (result.stderr or result.stdout).strip().splitlines()
    return [f"uv.lock is out of date: {detail[-1] if detail else 'run `uv lock`'}"]


def summary() -> dict[str, int]:
    return {
        "locked": len(locked()),
        "installed": len(installed()),
        "leftovers": len(leftovers()),
        "drift": len(lock_issues()),
    }


def uninstall(names: list[str]) -> int:
    """Remove the packages with uv; the project venv is the only thing touched."""
    uv = shutil.which("uv")
    if uv is None:
        print("[FAIL] uv is not on PATH; run the printed uninstall command yourself")
        return 1
    return subprocess.run(
        [uv, "pip", "uninstall", "--python", sys.executable, *names], cwd=project_cfg.BASE_DIR, check=False
    ).returncode


def main(remove: bool = False) -> int:
    found = leftovers()
    print(f"{len(found)} installed package(s) that no import or manifest declares")
    for name, version in found:
        print(f"  {name} {version}")
    if found and not remove:
        print("\nRemove with:\n  uv pip uninstall " + " ".join(name for name, _ in found))
    if found and remove:
        status = uninstall([name for name, _ in found])
        print(f"[{'OK' if status == 0 else 'FAIL'}] uninstall exited {status}")
    issues = lock_issues()
    print(f"\n{len(issues)} lock entry issue(s)")
    for issue in issues:
        print(f"  {issue}")
    return int(bool(issues))
