"""Select test classes affected by local changes using a one-hop reverse import walk.

Keeps test classes defined in a changed module or in a module that directly imports one. `--all`,
code edits to `FULL_TRIGGERS`, and a branch with no upstream run the full suite; a clean tree, a
non-Python change and an edit whose code is unchanged run no classes.

One hop is the deliberate trade: a second hop reaches most of the tree and costs more than running
everything, so a test two imports away waits for the full pre-push run. That run is also the backstop
for data the graph cannot see: it knows modules, so a change to a `.json`, template or config path
selects nothing on its own.

Dependency edges come from [import_graph](../shared/import_graph.py), parsed statically with `ast`
rather than imported. Dynamic imports and files executed via `subprocess`, `runpy`, or `open` are
not tracked by the module graph and rely on the full pre-push run.
"""

import ast
import unittest
from pathlib import Path
from typing import NamedTuple

from scripts.config import project_config as project_cfg
from scripts.shared.changes import NoUpstreamError, changed_since_upstream, git_text
from scripts.shared.import_graph import (
    REACH_DEPTH,
    find_affected_modules,
    import_graph,
    module_names,
    parse_source,
    parse_text,
)

FULL_TRIGGERS = frozenset(
    {
        # The files that decide what the suite is, and only when their code changes.
        "scripts/tests/registry.py",
        "scripts/tests/run.py",
        "scripts/tests/scoped_selection.py",
    }
)

# Alias for a test class rather than one of its instances, which is what the scope passes around.
TestClass = type[unittest.TestCase]


class Selection(NamedTuple):
    """The classes to run, the ones that stayed out, and the reason the scope is what it is."""

    kept: tuple[TestClass, ...]
    dropped: tuple[TestClass, ...]
    reason: str


def select_test_classes(
    test_classes: tuple[TestClass, ...],
    *,
    full: bool = False,
    change_set: list[str] | None = None,
    root: Path | None = None,
) -> Selection:
    """Partition `test_classes` into kept and dropped test classes for the current change set."""
    if full:
        return Selection(test_classes, (), "--all")
    if change_set is None:
        try:
            changed = changed_since_upstream(root)
        except NoUpstreamError:
            # There is no baseline to compare against, so there is no evidence and every class runs.
            return Selection(test_classes, (), "no upstream ref")
    else:
        changed = change_set
    # An empty set from git means the tree is clean, and its absence of evidence was the error above.
    if not changed:
        return Selection((), test_classes, "nothing changed")
    # An edit that leaves the code tree unchanged cannot change what a test observes, wherever it lands.
    code_changes = [path for path in changed if not ast_matches_upstream(path, root)]
    if not code_changes:
        return Selection((), test_classes, "no code change")

    triggers = FULL_TRIGGERS.intersection(code_changes)
    if triggers:
        return Selection(test_classes, (), f"manifest changed: {sorted(triggers)[0]}")

    # A document, config or batch path contributes no module, and neither does a `.py` outside `scripts/`.
    changed_modules = module_names(code_changes)
    if not changed_modules:
        return Selection((), test_classes, "no Python change")

    edges = import_graph(root)
    reachable = find_affected_modules(edges, changed_modules, depth=REACH_DEPTH)

    kept: list[TestClass] = []
    dropped: list[TestClass] = []
    for test_class in test_classes:
        if test_class.__module__ in reachable:
            kept.append(test_class)
        else:
            dropped.append(test_class)
    return Selection(tuple(kept), tuple(dropped), f"{len(reachable)} of {len(edges)} modules reachable")


def ast_matches_upstream(path: str, root: Path | None = None) -> bool:
    """Return whether a Python file's code matches its upstream branch, ignoring comments, docstrings and layout.

    Anything that is not Python source answers False, since there is no tree to compare, and so does a
    file whose upstream copy is missing, unreadable or unparsable: each counts as a real change.
    """
    if not path.endswith(".py"):
        return False
    base = project_cfg.BASE_DIR if root is None else root
    current = base / path
    if not current.is_file():
        return False
    # Read the committed version from the remote tracking branch for comparison.
    # `@{upstream}` is git's name for the branch this one tracks, not the tip of this branch.
    previous = git_text("show", "@{upstream}:" + path, root=root)
    # `ast.parse` discards `#` comments automatically; `_dump_without_docstrings` strips docstrings.
    before = parse_text(previous)
    after = parse_source(current)
    # No evidence from git is not proof of a prose edit: `git_text` answers "" when the read failed, and a
    # broken or unreadable file on either side is a real change too, since nothing can be ruled out.
    if not previous or before is None or after is None:
        return False
    # Equal trees after stripping prose means no test can observe the edit.
    return _dump_without_docstrings(before) == _dump_without_docstrings(after)


def _dump_without_docstrings(tree: ast.Module) -> str:
    """Return the AST dump of `tree` with its docstrings removed, mutating `tree` in place."""
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, scopes) or not node.body:
            continue
        if _is_docstring(node.body[0]):
            # Substitute `pass` when the docstring was the only statement in the body.
            node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree)


def _is_docstring(statement: ast.stmt) -> bool:
    """Whether a statement is a bare string, which is how a docstring is stored."""
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Constant):
        return False
    return isinstance(statement.value.value, str)
