"""The test classes the suite runs: test files are discovered, suite classes are listed.

A `test_*.py` file is discovered by parsing it for a top-level class whose base names `TestCase`, then
importing that module under the name its own path gives. Importing by a name built from a file path is
what `unittest` discovery does, and this repository bans that shape because the scope graph cannot see it;
the difference here is that the path is the input, so every discovered module is still a file the graph
knows.

A class in a module that is not `test_*.py` is part of a suite that also runs as a worker, so no file name
marks it as a test: those are listed in `SUITE_CLASSES`, where the choice is reviewed.

`TEST_CLASSES` is what the runner counts against and what the selector picks from.
"""

import ast
import importlib
import unittest
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.tests.cases.audiocpp.audio_comparison import AudioComparison
from scripts.tests.cases.coding_agents.shared.framework_clients import FrameworkClients
from scripts.tests.cases.koboldcpp.kobold_lite_streaming import StreamingPatch
from scripts.tests.cases.suites import frameworks_smoke
from scripts.tests.cases.suites.framework_update_additions import FrameworkUpdateAdditions
from scripts.tests.cases.suites.framework_updates import FrameworkUpdates
from scripts.tests.cases.suites.framework_updates_sources import FrameworkUpdateSources
from scripts.tests.cases.suites.hrx_fixes import FixStateTests
from scripts.tests.cases.suites.shared_contracts import SharedContracts

# - directories under `cases/` that hold no runnable classes
DISCOVERY_EXCLUSIONS = frozenset({"retired", "output"})


def test_module_name(path: Path) -> str:
    """The dotted module name a file under the repository is imported by."""
    relative = path.resolve().relative_to(project_cfg.BASE_DIR.resolve())
    return ".".join(relative.with_suffix("").parts)


def test_class_names(path: Path) -> list[str]:
    """Top-level classes in one test file whose base names a `TestCase`; parsed, never imported."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and any("TestCase" in ast.unparse(base) for base in node.bases)
    ]


def discover_test_classes() -> tuple[type[unittest.TestCase], ...]:
    """Every class in `cases/**/test_*.py`, in file order, imported by the name its path gives."""
    found: list[type[unittest.TestCase]] = []
    for path in sorted(project_cfg.TEST_CASES_DIR.rglob("test_*.py")):
        if any(part in DISCOVERY_EXCLUSIONS for part in path.parts):
            continue
        names = test_class_names(path)
        if not names:
            continue
        module = importlib.import_module(test_module_name(path))
        found.extend(getattr(module, name) for name in names)
    return tuple(found)


# - modules that are not `test_*.py`: a class here is a suite beside its worker, so it is named, not scanned
SUITE_CLASSES: tuple[type[unittest.TestCase], ...] = (
    AudioComparison,
    FrameworkClients,
    StreamingPatch,
    FrameworkUpdateAdditions,
    FrameworkUpdates,
    FrameworkUpdateSources,
    # - the launcher and proxy block is scoped like everything else: a change to that wiring keeps it,
    #   a change elsewhere leaves it to the push, so no class sits outside the graph
    *frameworks_smoke.DEFAULT_CLASSES,
    FixStateTests,
    SharedContracts,
)

TEST_CLASSES: tuple[type[unittest.TestCase], ...] = discover_test_classes() + SUITE_CLASSES
