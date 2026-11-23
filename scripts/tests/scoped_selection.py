"""Select the test classes a local change can affect, using a one-hop reverse import walk.

A class is kept when its module changed or directly imports a changed module. The full suite runs for
`--all`, a code change to a `FULL_TRIGGERS` file, a deleted Python file, or a branch with no upstream.
No classes run for a clean tree, an edit to comments, docstrings or layout only, or a change that
touches no Python module. The pre-push stage asks the same question through `python_code_changed`, so
a push that only edits comments or docstrings runs nothing either.

The walk takes a second hop only while the classes it would add stay under `SECOND_HOP_CLASS_CAP`,
because a wider reach costs more than the risk it covers; a test further away waits for the full
pre-push run.

Each call into `changes` or `import_graph` carries one line saying what it contributes here, since those
two modules own the detail; the rest of this file is the rule alone.

Edges come from parsing source with `ast`; nothing is imported. The graph only knows modules, so a
`.json`, template or config change selects nothing on its own, and dynamic imports and files reached
through `subprocess`, `runpy` or `open` are not tracked. The full pre-push run covers all of these.
"""

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.changes import GitError, NoUpstreamError, changed_since_upstream, upstream_texts
from scripts.shared.import_graph import (
    REACH_DEPTH,
    ImportGraph,
    ast_parse_text_or_file,
    find_affected_modules,
    import_graph,
    module_names,
)

# The files that decide what the suite is, and only when their code changes.
# `registry.py` lists the classes, `run.py` runs them, and this file holds the rule that picks from them.
FULL_TRIGGERS = {"scripts/tests/registry.py", "scripts/tests/run.py", "scripts/tests/scoped_selection.py"}

# A batch file names its module in text, so the graph cannot see the dependency. Any batch edit also
# selects the test that imports every module a batch names and asks each one for `--help`.
BATCH_LAUNCHER_TEST = "scripts.tests.cases.shared.gate.test_bat_launchers"

# A second hop is taken only while it stays under this many classes: the measured second-hop reach has a
# median of 2 classes and a mean of 9, and a hub that would exceed this is already near a full run.
SECOND_HOP_CLASS_CAP = 30


# Alias for a test class rather than one of its instances, which is what the scope passes around.
TestClass = type[unittest.TestCase]


# Frozen because a `Selection` is only ever a returned answer, never state that a caller updates.
@dataclass(frozen=True)
class Selection:
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
        # The push-stage baseline: the working tree against `HEAD`, plus the commits the upstream lacks.
        try:
            changed = changed_since_upstream(root)
        except NoUpstreamError:
            # There is no baseline to compare against, so there is no evidence and every class runs.
            return Selection(test_classes, (), "no upstream ref")
    else:
        changed = change_set
    # No changes means a clean tree; a missing baseline was already handled above.
    if not changed:
        return Selection((), test_classes, "nothing changed")
    # An edit that leaves the code tree unchanged cannot change what a test observes, wherever it lands.
    code_changes = code_change_paths(changed, root)
    if not code_changes:
        return Selection((), test_classes, "no code change")

    # Checked after the prose filter, so a comment edit inside `run.py` still runs nothing.
    triggers = FULL_TRIGGERS.intersection(code_changes)
    if triggers:
        first = min(triggers)
        return Selection(test_classes, (), f"manifest changed: {first}")

    # A deleted file is absent from the graph, so nothing links its importers to it and they would be missed.
    if _module_deleted(code_changes, root):
        return Selection(test_classes, (), "Python file deleted")

    # A document, config or batch path contributes no module, and neither does a `.py` outside `scripts/`.
    changed_modules = module_names(code_changes)
    # A batch file names its module in text, which the graph cannot see, so a batch edit selects the test
    # that imports every module a batch names. It starts nothing, and it costs under a second.
    batches = [path for path in code_changes if path.endswith(".bat")]
    if batches:
        changed_modules.add(BATCH_LAUNCHER_TEST)
    if not changed_modules:
        return Selection((), test_classes, "no Python change")

    # One pass over the tree: every module name mapped to the modules it imports, parsed from source.
    edges = import_graph(root)
    depth, reachable = _depth_and_reach(edges, changed_modules, test_classes)

    reason = _reach_reason(edges, reachable, code_changes, batches, depth)
    return _build_selection(test_classes, reachable, reason)


def _depth_and_reach(
    edges: ImportGraph, changed_modules: set[str], test_classes: tuple[TestClass, ...]
) -> tuple[int, set[str]]:
    """One hop, or a second one while the classes it adds stay under `SECOND_HOP_CLASS_CAP`."""
    reachable = find_affected_modules(edges, changed_modules, depth=REACH_DEPTH)
    deeper = find_affected_modules(edges, changed_modules, depth=REACH_DEPTH + 1)
    if sum(1 for test_class in test_classes if test_class.__module__ in deeper) <= SECOND_HOP_CLASS_CAP:
        return REACH_DEPTH + 1, deeper
    return REACH_DEPTH, reachable


def python_code_changed(paths: list[str], root: Path | None = None) -> bool:
    """Whether any changed Python file carries a code change; a document or config path never counts.

    The pre-push stage asks this, so a push that only edits Markdown, a batch file or configuration runs
    nothing, as it always did, and a `.py` edit that only touches prose stays cheap as well.
    """
    return bool(code_change_paths([path for path in paths if path.endswith(".py")], root))


def code_change_paths(paths: list[str], root: Path | None = None) -> list[str]:
    """The changed paths that carry a code change; a Python prose-only edit is left out.

    The pre-push stage asks this same question, so a push that only edits comments or docstrings stays
    fast instead of running the full suite for a file whose behavior did not change.
    """
    # Only `.py` paths can match upstream, so every other path stays for the caller to judge.
    if not paths:
        return []
    base = root or project_cfg.BASE_DIR
    readable = [path for path in paths if path.endswith(".py") and (base / path).is_file()]
    # The upstream copies come from one git call for the whole set. A read that fails is no evidence, so
    # every path counts as a change then, which is the same answer a missing copy gives. A path that is
    # gone from the tree is left out of the read: it is a change by definition, and git has nothing to
    # show for it, which `_code_changed_since_upstream` already answers.
    try:
        previous = upstream_texts(readable, root)
    except GitError:
        previous = {}
    return [path for path in paths if _code_changed_since_upstream(path, previous.get(path), root)]


def _code_changed_since_upstream(path: str, previous_source: str | None, root: Path | None = None) -> bool:
    """Return whether a file's code differs from `previous_source`, comments, docstrings and layout aside.

    True means a test can see the difference, which is how the selector reads it. Anything that is not
    Python source answers True, and so does a file whose upstream copy is missing or empty: those count as
    real changes rather than invisible ones.
    """
    if not path.endswith(".py"):
        return True
    current = (root or project_cfg.BASE_DIR) / path
    # A path that is no longer on disk cannot be compared, so it counts as a real change.
    if not current.is_file():
        return True
    # Nothing to compare against: None when git answered nothing, "" when the committed file is empty.
    if not previous_source:
        return True
    # The committed copy as a tree: source text from git, or None when it is empty or unparsable.
    committed = ast_parse_text_or_file(previous_source)
    # The working copy as a tree, parsed the same way, so the comparison is tree against tree.
    working = ast_parse_text_or_file(current)
    # A copy that will not parse is a real change as well, since nothing can be ruled out.
    if committed is None or working is None:
        return True
    # `ast.parse` drops comments and `_dump_without_docstrings` drops docstrings, so the two dumps hold only
    # code, and different dumps mean a test can observe the edit.
    return _dump_without_docstrings(committed) != _dump_without_docstrings(working)


def _build_selection(test_classes: tuple[TestClass, ...], reachable: set[str], reason: str) -> Selection:
    """The classes the reach covers, the ones it leaves out, and the sentence that explains it."""
    # `__module__` is the module a class was defined in, which is what the graph speaks.
    kept = tuple(test_class for test_class in test_classes if test_class.__module__ in reachable)
    dropped = tuple(test_class for test_class in test_classes if test_class.__module__ not in reachable)
    return Selection(kept=kept, dropped=dropped, reason=reason)


def _module_deleted(paths: list[str], root: Path | None) -> bool:
    """Whether any changed Python file is gone from the tree, which hides its importers from the graph."""
    base = root or project_cfg.BASE_DIR
    return any(path.endswith(".py") and not (base / path).is_file() for path in paths)


def _reach_reason(
    edges: ImportGraph,
    reachable: set[str],
    paths: list[str],
    batches: list[str] | None = None,
    depth: int = REACH_DEPTH,
) -> str:
    """The evidence a reader sees, including how many changed paths named no module."""
    # The change set holds unique paths, so the difference is exactly the ones that named no module.
    ignored = len(paths) - len(module_names(paths))
    detail = f" ({ignored} path(s) outside the module graph ignored)" if ignored else ""
    note = "; batch edit runs the launcher test" if batches else ""
    hops = f"; {depth} hops" if depth != REACH_DEPTH else ""
    return f"{len(reachable)} of {len(edges)} modules reachable{detail}{note}{hops}"


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
