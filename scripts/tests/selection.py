"""Which test classes a change can reach, from the import graph walked backwards.

The model-free suite holds well over a hundred classes, and most changes touch a few modules, so the
default run keeps the classes whose own module, or anything that module imports, sits in the changed
files' reverse import closure. Anything the graph cannot account for - a path outside `scripts/`, a
non-Python file, a manifest such as `scripts/tests/run.py` - keeps every class, because a wrong
omission hides a regression while a wrong inclusion only costs seconds.

The graph is parsed from source, never imported, so it stays model-free. It cannot see a dynamic
import or a file opened by string path; that blind spot is why the fallback is broad rather than
clever, and why `--all` exists.
"""

from __future__ import annotations

import ast
import unittest
from collections import deque
from pathlib import Path
from typing import NamedTuple

from scripts.config import project_config as project_cfg
from scripts.shared.changes import changed_paths, git

FULL_TRIGGERS = frozenset({"scripts/tests/run.py", "scripts/tests/selection.py"})


def module_name(path: str) -> str | None:
    """`scripts/x/y.py` becomes `scripts.x.y`, a package `__init__.py` names its package, anything else is None."""
    parts = Path(path).with_suffix("").parts
    if not parts or parts[0] != "scripts" or ".." in parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if len(parts) > 1 else None


def _target(node: ast.ImportFrom, module: str, is_package: bool) -> str | None:
    """The module a `from ... import ...` reads, resolving the dots against this module's package."""
    if not node.level:
        return node.module
    package = module if is_package else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if node.level - 1 > len(parts):
        return None
    base = ".".join(parts[: len(parts) - (node.level - 1)])
    return f"{base}.{node.module}" if node.module else base


def imported_names(path: Path, module: str) -> set[str]:
    """Every dotted name this file imports, relative imports resolved; an unparsable file imports nothing."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    is_package = path.name == "__init__.py"
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _target(node, module, is_package)
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _resolve(name: str, known: set[str]) -> str | None:
    """The module a dotted name refers to: the longest known prefix, since `from x.y import f` names no module."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None


def sources(root: Path | None = None) -> list[str]:
    """Tracked Python files under `scripts/`; the ignored state and test-output trees never enter the graph."""
    return [
        line
        for line in git("ls-files", "scripts", root=root).splitlines()
        if line.startswith("scripts/") and line.endswith(".py")
    ]


def graph(root: Path | None = None) -> dict[str, frozenset[str]]:
    """Module name to the modules it imports, for every tracked module under `scripts/`."""
    base = project_cfg.BASE_DIR if root is None else root
    base_paths = [base / path for path in sources() if (base / path).is_file()]
    files: dict[str, Path] = {}
    for path in base_paths:
        name = module_name(path.relative_to(base).as_posix())
        if name:
            files[name] = path
    known = set(files)
    return {
        name: frozenset(target for target in (_resolve(raw, known) for raw in imported_names(path, name)) if target)
        for name, path in files.items()
    }


def dependencies(edges: dict[str, frozenset[str]], module: str) -> frozenset[str]:
    """Everything this module reaches through imports, itself included."""
    seen: set[str] = set()
    queue = deque([module])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(edges.get(current, ()))
    return frozenset(seen)


def affected(edges: dict[str, frozenset[str]], changed: set[str]) -> frozenset[str]:
    """The changed modules plus every module that imports one, directly or through a chain."""
    importers: dict[str, set[str]] = {}
    for module, targets in edges.items():
        for target in targets:
            importers.setdefault(target, set()).add(module)
    seen: set[str] = set()
    queue = deque(changed)
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(importers.get(current, ()))
    return frozenset(seen)


class Selection(NamedTuple):
    """The classes to run, the ones that stayed out, and the reason the scope is what it is."""

    kept: tuple[type[unittest.TestCase], ...]
    dropped: tuple[type[unittest.TestCase], ...]
    why: str


def select(
    groups: tuple[type[unittest.TestCase], ...],
    *,
    full: bool = False,
    paths: list[str] | None = None,
    root: Path | None = None,
) -> Selection:
    """Keep the classes a change can reach; `full`, an empty change set or an unmodelled path keeps them all."""
    changed = changed_paths(root) if paths is None else paths
    if full:
        return Selection(groups, (), "--all")
    if not changed:
        return Selection(groups, (), "no change set")
    named = {path: module_name(path) for path in changed}
    unmodelled = sorted(path for path, name in named.items() if name is None)
    if unmodelled:
        return Selection(groups, (), f"not a Python module: {unmodelled[0]}")
    if triggers := FULL_TRIGGERS.intersection(changed):
        return Selection(groups, (), f"manifest changed: {sorted(triggers)[0]}")
    edges = graph(root)
    # - a module git has not seen yet still reaches the classes that import it
    for name in named.values():
        if name:
            edges.setdefault(name, frozenset())
    reach = affected(edges, {name for name in named.values() if name})
    kept = tuple(group for group in groups if dependencies(edges, group.__module__) & reach)
    dropped = tuple(group for group in groups if group not in kept)
    return Selection(kept, dropped, f"{len(reach)} of {len(edges)} modules reachable")
