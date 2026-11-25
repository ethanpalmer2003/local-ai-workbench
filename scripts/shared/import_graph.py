"""Static import graph for Python modules under `scripts/`.

Parses tracked and non-ignored untracked `.py` files with `ast` without importing them. Each
module's dependencies are its resolved imports and its existing parent packages. Unreadable or
unparsable files yield no edges and are caught separately by `ruff` and `pyright`.
"""

import ast
from collections.abc import Iterable
from pathlib import Path

import networkx as nx

from scripts.config import project_config as project_cfg
from scripts.shared.file_sets import git_text

# A directed graph of module names, one edge per import and per parent package.
ImportGraph = nx.DiGraph
# The deepest hop that is still much cheaper than a full run: depth 0 would miss the direct importers, and
# depth 2 costs close to a full run for a widely imported module, so everything past here may as well be
# the full push run.
REACH_DEPTH = 1


def import_graph(root: Path | None = None) -> ImportGraph:
    """Build a map of module name to the modules it depends on for every module under `scripts/` that git lists.

    A dependency is an imported module or a known parent package (whose `__init__.py` runs on import).
    """
    files = git_module_files(root)
    known = set(files)
    graph: ImportGraph = nx.DiGraph()
    graph.add_nodes_from(files)
    for name, path in files.items():
        parts = name.split(".")
        targets = {".".join(parts[:end]) for end in range(1, len(parts))} & known
        tree = ast_parse_text_or_file(path)
        if tree is not None:
            for raw in imported_names(tree, name, is_package=path.name == "__init__.py"):
                target = _longest_known_prefix(raw, known)
                if target:
                    targets.add(target)
        graph.add_edges_from((name, target) for target in targets - {name})
    return graph


def find_affected_modules(edges: ImportGraph, changed: Iterable[str], *, depth: int | None = None) -> set[str]:
    """Return the changed modules and every module in `edges` that depends on them, walking up to `depth` hops.

    `depth=1` keeps the changed modules and their direct importers, while `None` walks the whole chain.
    """
    # The edges point at dependencies, so the walk goes against them to reach the importers.
    importers = edges.reverse(copy=False)
    radius = len(importers) if depth is None else depth
    seen: set[str] = set()
    for module in changed:
        if module in importers:
            seen.update(nx.ego_graph(importers, module, radius=radius).nodes)
        else:
            seen.add(module)
    return seen


def module_names(paths: Iterable[str]) -> set[str]:
    """The module names among these paths, leaving out every path that is not a module."""
    names: set[str] = set()
    for path in paths:
        name = _module_name(path)
        if name:
            names.add(name)
    return names


def git_module_files(root: Path | None = None) -> dict[str, Path]:
    """Map module names to source files for every module under `scripts/` that git lists.

    `--cached` is required alongside `--others`: `--others` alone lists untracked files only.
    Ignored state and test-output trees never enter the graph.
    """
    base = project_cfg.BASE_DIR if root is None else root
    files: dict[str, Path] = {}
    for relative in git_text(
        "ls-files", "--cached", "--others", "--exclude-standard", "scripts", root=root
    ).splitlines():
        name = _module_name(relative)
        path = base / relative
        if name and path.is_file():
            files[name] = path
    return files


def _module_name(path: str) -> str | None:
    """Convert `scripts/x/y.py` to `scripts.x.y`, package `__init__.py` to its package, or anything else to None.

    A document, template or config path is not a module even under `scripts/`, so it contributes no node.
    A package takes its directory name: `scripts/tests/__init__.py` becomes `scripts.tests`, the node
    `from scripts.tests import run` already names.
    """
    if not path.endswith(".py"):
        return None
    parts = Path(path).with_suffix("").parts
    # `..` reaches this guard only from a caller building a path, since no tracked file climbs out.
    if not parts or parts[0] != "scripts" or ".." in parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    # `scripts` is the root of the map rather than a module, so a name needs a segment under it.
    return ".".join(parts) if len(parts) > 1 else None


def ast_parse_text_or_file(source: str | Path) -> ast.Module | None:
    """Return the syntax tree of source text or of a file, or None when it is empty or unparsable.

    A `str` is read as source text and a `Path` as a file, so a path written as a string would be parsed as
    code rather than read.
    """
    try:
        text = source if isinstance(source, str) else source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.strip():
        return None
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def imported_names(tree: ast.Module, module: str, *, is_package: bool) -> set[str]:
    """Return every dotted name a file imports, with relative imports resolved.

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


def module_paths(modules: Iterable[str], root: Path | None = None) -> list[str]:
    """Return sorted repo-relative source paths for the given modules that git lists and the tree holds."""
    base = project_cfg.BASE_DIR if root is None else root
    files = git_module_files(root)
    return sorted(files[module].relative_to(base).as_posix() for module in modules if module in files)


def _from_import_target(node: ast.ImportFrom, module: str, is_package: bool) -> str | None:
    """Resolve the target module of a `from ... import ...` node against the current module's package.

    Returns None when relative dots climb past the top-level package.
    """
    if not node.level:
        return node.module
    package = module if is_package else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    # `node.level` is the dot count: 1 (`from . import x`) stays in `package`, 2 climbs one parent up.
    up = node.level - 1
    if up >= len(parts):
        return None
    base = ".".join(parts[: len(parts) - up])
    return f"{base}.{node.module}" if node.module else base


def _longest_known_prefix(name: str, known: set[str]) -> str | None:
    """Resolve a dotted import name to the longest prefix that matches a known module."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None
