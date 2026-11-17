"""The import graph of `scripts/`, parsed from source and never imported.

One owner for the answer, because the scoped test run and the scoped type check both ask it what a
change reaches. Every Python file under `scripts/` that exists on disk contributes a node, tracked or
untracked-but-not-ignored, and its dependencies are the modules it imports and the packages above it.
An unreadable or unparsable file contributes no dependencies, which is why the gate's ruff and pyright
refuse such a file first.
"""

import ast
from collections import deque
from collections.abc import Iterable
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.changes import git

Graph = dict[str, frozenset[str]]
# One import hop: what a change can break without transitive guessing, used by the suite's scope
# and by the type check that runs beside it.
REACH_DEPTH = 1


def module_name(path: str) -> str | None:
    """Convert `scripts/x/y.py` to `scripts.x.y`, package `__init__.py` to its package, or anything else to None.

    A document, template or config path is not a module even under `scripts/`, so it contributes no node.
    """
    if not path.endswith(".py"):
        return None
    parts = Path(path).with_suffix("").parts
    if not parts or parts[0] != "scripts" or ".." in parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if len(parts) > 1 else None


def module_files(root: Path | None = None) -> dict[str, Path]:
    """Map module names to source files for every module under `scripts/` that exists on disk.

    `--cached` is required alongside `--others`: `--others` alone lists untracked files only.
    Ignored state and test-output trees never enter the graph.
    """
    base = project_cfg.BASE_DIR if root is None else root
    files: dict[str, Path] = {}
    for relative in git("ls-files", "--cached", "--others", "--exclude-standard", "scripts", root=root).splitlines():
        name = module_name(relative)
        path = base / relative
        if name and path.is_file():
            files[name] = path
    return files


def parse_source(path: Path) -> ast.Module | None:
    """Parse and return the syntax tree of a source file, or None when it cannot be read or parsed."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


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


def _longest_known_prefix(name: str, known: set[str]) -> str | None:
    """Resolve a dotted import name to the longest prefix that matches a known module."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None


def import_graph(root: Path | None = None) -> Graph:
    """Build a map of module name to the modules it depends on for every module under `scripts/` on disk.

    A dependency is an imported module or a known parent package (whose `__init__.py` runs on import).
    """
    files = module_files(root)
    known = set(files)
    edges: Graph = {}
    for name, path in files.items():
        parts = name.split(".")
        parents = {".".join(parts[:end]) for end in range(1, len(parts))}
        targets = parents & known
        tree = parse_source(path)
        if tree is not None:
            for raw in imported_names(tree, name, is_package=path.name == "__init__.py"):
                target = _longest_known_prefix(raw, known)
                if target:
                    targets.add(target)
        edges[name] = frozenset(targets - {name})
    return edges


def reverse_closure(edges: Graph, changed: Iterable[str], *, depth: int | None = None) -> frozenset[str]:
    """Return the changed modules plus every module that depends on them, walking up to `depth` hops.

    `depth=1` keeps the changed modules and their direct importers, while `None` walks the whole chain.
    """
    # Invert the forward dependency graph so each module maps to the modules that import it.
    importers: dict[str, set[str]] = {}
    for module, targets in edges.items():
        for target in targets:
            importers.setdefault(target, set()).add(module)

    # Breadth-first search outward from `changed`, stopping at `depth` hops when specified.
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


def module_paths(modules: Iterable[str], root: Path | None = None) -> list[str]:
    """Return sorted repo-relative source paths for the given modules that exist on disk."""
    base = project_cfg.BASE_DIR if root is None else root
    files = module_files(root)
    return sorted(files[module].relative_to(base).as_posix() for module in modules if module in files)
