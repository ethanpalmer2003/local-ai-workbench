"""Which test classes a change can reach, from the import graph walked one hop backwards.

The default run is a feedback loop, not a guarantee: one hop back from the change keeps the classes
whose module changed or imports a changed module, and the full run at push catches the rest. A change
set with no Python module runs no class, while an empty one keeps them all; a comment or docstring edit
runs nothing wherever it lands, and `FULL_TRIGGERS` keeps every class when its own code changes.

The graph belongs to [import_graph](../shared/import_graph.py): parsed from source, never imported, one
node per Python file under `scripts/`. A module name assembled at runtime cannot be read here at all,
which is why the gate refuses a dynamic import outright; a file reached through `subprocess`, `runpy` or
`open` stays invisible.
"""

import ast
import unittest
from pathlib import Path
from typing import NamedTuple

from scripts.config import project_config as project_cfg
from scripts.shared.changes import changed_paths, git
from scripts.shared.import_graph import REACH_DEPTH, import_graph, module_name, parse_source, reverse_closure

FULL_TRIGGERS = frozenset(
    {
        # The two files that decide what the suite is, and only when their code changes.
        "scripts/tests/run.py",
        "scripts/tests/scoped_selection.py",
    }
)

TestGroup = type[unittest.TestCase]


def _without_docstrings(tree: ast.Module) -> str:
    """Return the AST dump with docstrings removed, so a comment or docstring edit compares equal."""
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, scopes) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            # Substitute `pass` when the docstring was the only statement in the body.
            node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree)


def cosmetic_only(path: str, root: Path | None = None) -> bool:
    """Return whether a Python file differs from upstream only in comments or docstrings.

    If upstream is missing or the comparison fails, it counts as a real change. New, deleted, unreadable,
    or unparsable files also count as real changes.
    """
    base = project_cfg.BASE_DIR if root is None else root
    current = base / path
    if not current.is_file():
        return False
    # Read the committed version from the remote tracking branch for comparison.
    previous = git("show", "@{upstream}:" + path, root=root)
    try:
        # `ast.parse` discards `#` comments automatically; `_without_docstrings` strips docstrings.
        before = ast.parse(previous)
        after = parse_source(current)
    except (SyntaxError, ValueError):
        return False
    if after is None:
        return False
    return _without_docstrings(before) == _without_docstrings(after)


class Selection(NamedTuple):
    """The classes to run, the ones that stayed out, and the reason the scope is what it is."""

    kept: tuple[TestGroup, ...]
    dropped: tuple[TestGroup, ...]
    why: str


def select(
    groups: tuple[TestGroup, ...], *, full: bool = False, paths: list[str] | None = None, root: Path | None = None
) -> Selection:
    """Keep the classes a Python change can reach; a change set with no Python module runs no class.

    A class is kept if its module is in the reverse closure of the changed modules. A document, config
    or batch path contributes no module, so it neither narrows nor widens the run; `FULL_TRIGGERS` keeps
    every class when its own code changes, and `--all` always does.
    """
    if full:
        return Selection(groups, (), "--all")
    changed = changed_paths(root) if paths is None else paths
    if not changed:
        return Selection(groups, (), "no change set")
    # A comment or docstring edit changes nothing a test can see, wherever it lands.
    changed = [path for path in changed if not (path.endswith(".py") and cosmetic_only(path, root))]
    if not changed:
        return Selection((), groups, "comment or docstring only")

    triggers = FULL_TRIGGERS.intersection(changed)
    if triggers:
        return Selection(groups, (), f"manifest changed: {sorted(triggers)[0]}")

    changed_modules: set[str] = set()
    for path in changed:
        name = module_name(path)
        if name:
            changed_modules.add(name)
    if not changed_modules:
        return Selection((), groups, "no Python change")

    edges = import_graph(root)
    reachable = reverse_closure(edges, changed_modules, depth=REACH_DEPTH)

    kept: list[TestGroup] = []
    dropped: list[TestGroup] = []
    for group in groups:
        if group.__module__ in reachable:
            kept.append(group)
        else:
            dropped.append(group)
    return Selection(tuple(kept), tuple(dropped), f"{len(reachable)} of {len(edges)} modules reachable")
