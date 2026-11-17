"""Which test classes a change can reach, from the import graph walked one hop backwards.

The default run is a feedback loop, not a guarantee: it keeps the classes whose module changed or
imports a changed module, one hop only, and the full run before a push is what catches the rest. Only
a Python module narrows the run: a document, batch file, config or other path contributes no module,
so a change set with no Python path runs no class. The two manifests in `FULL_TRIGGERS` keep every
class when their code changes - a comment or docstring edit to one decides nothing - and `--all` runs
everything.

The graph is parsed from source, never imported, so it stays model-free. Importing `scripts.x.y` also
runs `scripts/x/__init__.py`, so every module gets an edge to each of its parent packages. Three gaps
remain and they are not equal: a module name assembled at runtime, and a Python file reached through
`subprocess`, `runpy` or `open`, are invisible to the graph; an unreadable or unparsable file gets no
edges at all. That last one is silent to this module - a change below a broken file can drop a class
above it - and is caught one step earlier instead, because ruff and pyright fail the gate on any
maintained file that does not parse. A new module git has not seen resolves to its parent package.
"""

from __future__ import annotations

import ast
import unittest
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from scripts.config import project_config as project_cfg
from scripts.shared.changes import changed_paths, git

FULL_TRIGGERS = frozenset(
    {
        # - the two files that decide what the suite is, and only when their code changes
        "scripts/tests/run.py",
        "scripts/tests/selection.py",
    }
)
# - the default scope stops here: the full run before a push is what catches a transitive miss
SCOPE_DEPTH = 1

Graph = dict[str, frozenset[str]]
TestGroup = type[unittest.TestCase]


# --- Mapping files to module names ---------------------------------------------------------------


def module_name(path: str) -> str | None:
    """`scripts/x/y.py` becomes `scripts.x.y`, a package `__init__.py` names its package, anything else is None.

    A document, template or config path is not a module even under `scripts/`, so it neither narrows the
    run nor asks for the full suite.
    """
    if not path.endswith(".py"):
        return None
    parts = Path(path).with_suffix("").parts
    if not parts or parts[0] != "scripts" or ".." in parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if len(parts) > 1 else None


def tracked_sources(root: Path | None = None) -> list[str]:
    """Tracked Python files under `scripts/`; the ignored state and test-output trees never enter the graph."""
    return [
        line
        for line in git("ls-files", "scripts", root=root).splitlines()
        if line.startswith("scripts/") and line.endswith(".py")
    ]


def module_files(root: Path | None = None) -> dict[str, Path]:
    """Module name to source file, for every tracked module under `scripts/` that still exists on disk."""
    base = project_cfg.BASE_DIR if root is None else root
    files: dict[str, Path] = {}
    for relative in tracked_sources(root):
        path = base / relative
        name = module_name(relative)
        if name and path.is_file():
            files[name] = path
    return files


def _without_docstrings(tree: ast.Module) -> str:
    """The tree as text with every docstring blanked, so a comment or docstring edit compares equal."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree)


def cosmetic_only(path: str, root: Path | None = None) -> bool:
    """Whether a Python file differs from upstream only in comments or docstrings.

    A manifest such as `run.py` decides what the suite is, but only through its code: a comment or a
    docstring edit changes nothing a test can see, so it should not drag in every class. A file that is
    new, deleted, unreadable or unparsable on either side counts as a real change.
    """
    base = project_cfg.BASE_DIR if root is None else root
    current = base / path
    if not current.is_file():
        return False
    previous = git("show", f"@{{upstream}}:{path}", root=root)
    try:
        before = ast.parse(previous)
        after = _parse(current)
    except (SyntaxError, ValueError):
        return False
    if after is None:
        return False
    return _without_docstrings(before) == _without_docstrings(after)


# --- Reading dependencies out of one file --------------------------------------------------------


def _parse(path: Path) -> ast.Module | None:
    """The syntax tree of a source file, or None when it cannot be read or parsed."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _from_import_target(node: ast.ImportFrom, module: str, is_package: bool) -> str | None:
    """The module a `from ... import ...` reads, resolving the dots against this module's package.

    Returns None when the dots climb out of the top-level package, because no module has that name.
    """
    if not node.level:
        return node.module
    package = module if is_package else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if node.level - 1 >= len(parts):
        return None
    base = ".".join(parts[: len(parts) - (node.level - 1)])
    return f"{base}.{node.module}" if node.module else base


def imported_names(tree: ast.Module, module: str, *, is_package: bool) -> set[str]:
    """Every dotted name a file imports, relative imports resolved.

    `from x import y` yields both `x` and `x.y`, because `y` may be a submodule or just a name in `x`.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _from_import_target(node, module, is_package)
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def literal_targets(tree: ast.Module, known: set[str]) -> set[str]:
    """Dotted module names a file spells in a string, because a dynamic import hides its target.

    `importlib.import_module("scripts.x")` has no import statement to read, so a string constant that
    matches a known module is treated as a dependency. A name assembled at runtime stays invisible,
    which is one of the gaps `--all` covers.
    """
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in known
    }


def _longest_known_prefix(name: str, known: set[str]) -> str | None:
    """The module a dotted name refers to: the longest known prefix, since `from x.y import f` names no module."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None


def _parent_packages(module: str, known: set[str]) -> set[str]:
    """The known packages above a module, whose `__init__.py` runs whenever the module is imported."""
    parts = module.split(".")
    return {parent for end in range(1, len(parts)) if (parent := ".".join(parts[:end])) in known}


# --- The graph and the queries on it -------------------------------------------------------------


def import_graph(root: Path | None = None) -> Graph:
    """Module name to the modules it depends on, for every tracked module under `scripts/`.

    A dependency is an import, a string naming a known module, or a parent package.
    """
    files = module_files(root)
    known = set(files)
    edges: Graph = {}
    for name, path in files.items():
        targets = _parent_packages(name, known)
        tree = _parse(path)
        if tree is not None:
            raw_names = imported_names(tree, name, is_package=path.name == "__init__.py")
            targets |= {target for raw in raw_names if (target := _longest_known_prefix(raw, known))}
            targets |= literal_targets(tree, known)
        edges[name] = frozenset(targets - {name})
    return edges


def reverse_closure(edges: Graph, changed: Iterable[str], *, depth: int | None = None) -> frozenset[str]:
    """The changed modules plus every module that depends on one, one hop at a time.

    `depth` stops the walk before the next hop: 1 keeps the direct importers only, and None walks the
    whole chain. The default scope uses one hop, because the full run before a push is the guarantee.
    """
    importers: dict[str, set[str]] = {}
    for module, targets in edges.items():
        for target in targets:
            importers.setdefault(target, set()).add(module)
    seen: set[str] = set()
    queue = deque((module, 0) for module in changed)
    while queue:
        current, level = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        if depth is not None and level >= depth:
            continue
        queue.extend((importer, level + 1) for importer in importers.get(current, ()))
    return frozenset(seen)


# --- Choosing the classes ------------------------------------------------------------------------


class Selection(NamedTuple):
    """The classes to run, the ones that stayed out, and the reason the scope is what it is."""

    kept: tuple[TestGroup, ...]
    dropped: tuple[TestGroup, ...]
    why: str


def select(
    groups: tuple[TestGroup, ...], *, full: bool = False, paths: list[str] | None = None, root: Path | None = None
) -> Selection:
    """Keep the classes a Python change can reach; a change set with no Python path runs no class.

    A class is reachable when its module is in the reverse closure of the changed modules. That is
    equivalent to its dependencies overlapping the closure, and needs one search instead of one per class.
    A document, config or batch path contributes no module, so it neither narrows nor widens the run;
    `FULL_TRIGGERS` and `--all` are the only ways to ask for every class.
    """
    if full:
        return Selection(groups, (), "--all")
    changed = changed_paths(root) if paths is None else paths
    if not changed:
        return Selection(groups, (), "no change set")
    # - a trigger decides what the suite is, but a comment or docstring edit to it decides nothing
    changed = [
        path for path in changed if not (path in FULL_TRIGGERS and path.endswith(".py") and cosmetic_only(path, root))
    ]
    if not changed:
        return Selection((), groups, "comment or docstring only")
    if triggers := FULL_TRIGGERS.intersection(changed):
        return Selection(groups, (), f"manifest changed: {sorted(triggers)[0]}")

    changed_modules = {name for path in changed if (name := module_name(path))}
    if not changed_modules:
        return Selection((), groups, "no Python change")

    edges = import_graph(root)
    # A module git has not seen yet still reaches the classes that import it.
    for name in changed_modules:
        edges.setdefault(name, frozenset())
    reachable = reverse_closure(edges, changed_modules, depth=SCOPE_DEPTH)

    kept: list[TestGroup] = []
    dropped: list[TestGroup] = []
    for group in groups:
        (kept if group.__module__ in reachable else dropped).append(group)
    return Selection(tuple(kept), tuple(dropped), f"{len(reachable)} of {len(edges)} modules reachable")
