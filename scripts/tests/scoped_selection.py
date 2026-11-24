"""Select the test classes a local change can affect, using a one-hop reverse import walk.

A class is kept when its module changed or directly imports a changed module. The full suite runs for
`--all`, a code change to a `FULL_TRIGGERS` file, a deleted Python file, or a branch with no upstream.
No classes run for a clean tree, an edit to comments, docstrings or layout only, or a change that
touches no Python module. The pre-push stage asks the same question through `python_code_changed` in
`shared/code_changes.py`, so a push that only edits comments or docstrings runs nothing either.

The walk keeps adding hops while the classes in reach stay under `HOP_CLASS_CAP`, so a dependent a few
imports away is included while it is cheap; a hub stops at one hop and waits for the full pre-push run.

Each call into `changes`, `code_changes` or `import_graph` carries one line saying what it contributes
here, since those three modules own the detail; the rest of this file is the rule alone.

Edges come from parsing source with `ast`; nothing is imported. The graph only knows modules, so a
`.json`, template or config change selects nothing on its own, and dynamic imports and files reached
through `subprocess`, `runpy` or `open` are not tracked. The full pre-push run covers all of these.
"""

import unittest
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.changes import NoUpstreamError, changed_since_upstream
from scripts.shared.code_changes import paths_with_code_changes
from scripts.shared.import_graph import REACH_DEPTH, ImportGraph, find_affected_modules, import_graph, module_names

# The files that decide what the suite is, and only when their code changes.
# `registry.py` lists the classes, `run.py` runs them, and this file holds the rule that picks from them.
FULL_TRIGGERS = {"scripts/tests/registry.py", "scripts/tests/run.py", "scripts/tests/scoped_selection.py"}

# A batch file names its module in text, so the graph cannot see the dependency. Any batch edit also
# selects the test that imports every module a batch names and asks each one for `--help`.
BATCH_LAUNCHER_TEST = "scripts.tests.cases.shared.gate.test_bat_launchers"

# The walk keeps adding hops while the classes in reach stay under this cap: measured over the tree, a hop
# adds a median of 0 and a mean of about 1 class, so the cap is what keeps a hub from costing a full run.
HOP_CLASS_CAP = 30


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
    code_changes = paths_with_code_changes(changed, root)
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
    """The deepest reach whose classes stay under `HOP_CLASS_CAP`, stopping when no hop adds a module."""
    depth = REACH_DEPTH
    reachable = find_affected_modules(edges, changed_modules, depth=depth)
    while True:
        deeper = find_affected_modules(edges, changed_modules, depth=depth + 1)
        # - a saturated walk would only repeat itself, so the depth is the graph's own limit, not a ceiling
        if deeper == reachable:
            return depth, reachable
        if sum(1 for test_class in test_classes if test_class.__module__ in deeper) > HOP_CLASS_CAP:
            return depth, reachable
        depth, reachable = depth + 1, deeper


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
