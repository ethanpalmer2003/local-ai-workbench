"""Select the test classes a local change can affect, using a one-hop reverse import walk.

A class is kept when its module changed or directly imports a changed module. The full suite runs for
`--all`, a code change to a `FULL_TRIGGERS` file, a deleted Python file, or a branch with no upstream.
No classes run for a clean tree, an edit to comments, docstrings or layout only, or a change that
touches no Python module.

The walk is currently set to one hop because a second hop was tested and found to select close to a
full run. A test two imports away waits for the full pre-push run.

Edges come from parsing source with `ast`; nothing is imported. The graph only knows modules, so a
`.json`, template or config change selects nothing on its own, and dynamic imports and files reached
through `subprocess`, `runpy` or `open` are not tracked. The full pre-push run covers all of these.
"""

import ast
import unittest
from pathlib import Path
from typing import NamedTuple

from scripts.config import project_config as project_cfg
from scripts.shared.changes import NoUpstreamError, changed_since_upstream, git_text_or_empty
from scripts.shared.import_graph import (
    REACH_DEPTH,
    ImportGraph,
    find_affected_modules,
    import_graph,
    module_name,
    module_names,
    parse,
)

FULL_TRIGGERS = frozenset(
    {
        # The files that decide what the suite is, and only when their code changes.
        # `registry.py` lists the classes, `run.py` runs them, and this file holds the rule that picks from them.
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
    # Only `.py` paths can match upstream, so every other path stays for the module check below to judge.
    code_changes = [path for path in changed if code_changed_since_upstream(path, root)]
    if not code_changes:
        return Selection((), test_classes, "no code change")

    # Checked after the prose filter, so a comment edit inside `run.py` still runs nothing.
    triggers = FULL_TRIGGERS.intersection(code_changes)
    if triggers:
        return Selection(test_classes, (), f"manifest changed: {sorted(triggers)[0]}")

    # A deleted file is absent from the graph, so nothing links its importers to it and they would be missed.
    if _module_deleted(code_changes, root):
        return Selection(test_classes, (), "Python file deleted")

    # A document, config or batch path contributes no module, and neither does a `.py` outside `scripts/`.
    changed_modules = module_names(code_changes)
    if not changed_modules:
        return Selection((), test_classes, "no Python change")

    edges = import_graph(root)
    # The walk is a breadth-first search over the reversed graph, one hop back by default.
    reachable = find_affected_modules(edges, changed_modules, depth=REACH_DEPTH)

    return _partition(test_classes, reachable, _reach_reason(edges, reachable, code_changes))


def code_changed_since_upstream(path: str, root: Path | None = None) -> bool:
    """Return whether a file's code differs from its upstream copy, comments, docstrings and layout aside.

    True means a test can see the difference, which is how the selector reads it. Anything that is not
    Python source answers True, and so does a file whose upstream copy is missing, unreadable or
    unparsable: those count as real changes rather than invisible ones.
    """
    if not path.endswith(".py"):
        return True
    base = project_cfg.BASE_DIR if root is None else root
    current = base / path
    # A path that is no longer on disk cannot be compared, so it counts as a real change.
    if not current.is_file():
        return True
    # Read the committed version from the remote tracking branch for comparison.
    # `@{upstream}` is git's name for the branch this one tracks, not the tip of this branch.
    previous = git_text_or_empty("show", "@{upstream}:" + path, root=root)
    # `ast.parse` discards `#` comments automatically; `_dump_without_docstrings` strips docstrings.
    before = parse(previous)
    after = parse(current)
    # No evidence from git is not proof of a prose edit: `git_text_or_empty` answers "" when the read failed, and
    # broken or unreadable file on either side is a real change too, since nothing can be ruled out.
    if not previous or before is None or after is None:
        return True
    # Different trees after stripping prose means a test can observe the edit.
    return _dump_without_docstrings(before) != _dump_without_docstrings(after)


def _partition(test_classes: tuple[TestClass, ...], reachable: frozenset[str], reason: str) -> Selection:
    """The classes the reach covers, the ones it leaves out, and the sentence that explains it."""
    # `__module__` is the module a class was defined in, which is what the graph speaks.
    kept = tuple(test_class for test_class in test_classes if test_class.__module__ in reachable)
    dropped = tuple(test_class for test_class in test_classes if test_class.__module__ not in reachable)
    return Selection(kept=kept, dropped=dropped, reason=reason)


def _module_deleted(paths: list[str], root: Path | None) -> bool:
    """Whether any changed Python file is gone from the tree, which hides its importers from the graph."""
    base = project_cfg.BASE_DIR if root is None else root
    return any(path.endswith(".py") and not (base / path).is_file() for path in paths)


def _reach_reason(edges: ImportGraph, reachable: frozenset[str], paths: list[str]) -> str:
    """The evidence a reader sees, including how many changed paths named no module."""
    ignored = sum(module_name(path) is None for path in paths)
    detail = f" ({ignored} path(s) outside the module graph ignored)" if ignored else ""
    return f"{len(reachable)} of {len(edges)} modules reachable{detail}"


def _dump_without_docstrings(tree: ast.Module) -> str:
    """Return the AST dump of `tree` with its docstrings removed, mutating `tree` in place."""
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, scopes) or not node.body:
            continue
        if _is_docstring(node.body[0]):
            # Substitute `pass` when it was the only statement, so a docstring-only body compares equal to one
            # holding `pass`.
            node.body = node.body[1:] or [ast.Pass()]
    # `ast.dump` leaves out line and column numbers, which is why moving or reformatting code compares equal.
    return ast.dump(tree)


def _is_docstring(statement: ast.stmt) -> bool:
    """Whether a statement is a bare string, which is how a docstring is stored."""
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Constant):
        return False
    return isinstance(statement.value.value, str)
