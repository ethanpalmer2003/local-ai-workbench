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


def module_name(path: str) -> str | None:
    """`scripts/x/y.py` becomes `scripts.x.y`, a package `__init__.py` names its package, anything else is None.

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


def source_files(root: Path | None = None) -> list[str]:
    """Every Python file under `scripts/` on disk, tracked or untracked-but-not-ignored.

    `--cached` is required: `--others` alone lists untracked files only. The ignored state and
    test-output trees never enter the graph.
    """
    return [
        line
        for line in git("ls-files", "--cached", "--others", "--exclude-standard", "scripts", root=root).splitlines()
        if line.startswith("scripts/") and line.endswith(".py")
    ]


def module_files(root: Path | None = None) -> dict[str, Path]:
    """Module name to source file, for every module under `scripts/` that exists on disk."""
    base = project_cfg.BASE_DIR if root is None else root
    files: dict[str, Path] = {}
    for relative in source_files(root):
        path = base / relative
        name = module_name(relative)
        if name and path.is_file():
            files[name] = path
    return files


def parse_source(path: Path) -> ast.Module | None:
    """The syntax tree of a source file, or None when it cannot be read or parsed."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def from_import_target(node: ast.ImportFrom, module: str, is_package: bool) -> str | None:
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
            base = from_import_target(node, module, is_package)
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def longest_known_prefix(name: str, known: set[str]) -> str | None:
    """The module a dotted name refers to: the longest known prefix, since `from x.y import f` names no module."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None


def parent_packages(module: str, known: set[str]) -> set[str]:
    """The known packages above a module, whose `__init__.py` runs whenever the module is imported."""
    parts = module.split(".")
    return {parent for end in range(1, len(parts)) if (parent := ".".join(parts[:end])) in known}


def import_graph(root: Path | None = None) -> Graph:
    """Module name to the modules it depends on, for every module under `scripts/` on disk.

    A dependency is an import or a parent package.
    """
    files = module_files(root)
    known = set(files)
    edges: Graph = {}
    for name, path in files.items():
        targets = parent_packages(name, known)
        tree = parse_source(path)
        if tree is not None:
            raw_names = imported_names(tree, name, is_package=path.name == "__init__.py")
            targets |= {target for raw in raw_names if (target := longest_known_prefix(raw, known))}
        edges[name] = frozenset(targets - {name})
    return edges


def reverse_closure(edges: Graph, changed: Iterable[str], *, depth: int | None = None) -> frozenset[str]:
    """The changed modules plus every module that depends on one, one hop at a time.

    `depth` stops the walk: depth 1 keeps the changed modules and their direct importers, while None walks the
    whole chain.
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


def module_paths(modules: Iterable[str], root: Path | None = None) -> list[str]:
    """Repo-relative source paths for the modules that still exist on disk, for a tool that reads files."""
    base = project_cfg.BASE_DIR if root is None else root
    files = module_files(root)
    return sorted(files[module].relative_to(base).as_posix() for module in modules if module in files)
