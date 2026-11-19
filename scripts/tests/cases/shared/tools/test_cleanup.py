"""The cleanup keeps what a decision cites and weights history by how expensive a run was."""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.config import project_config as project_cfg
from scripts.tools import cleanup


def _run(root: Path, area: str, stamp: str, age_days: int) -> Path:
    """Create a run directory two levels under `area` with a chosen age."""
    run = root / area / "case" / "unreviewed" / stamp
    run.mkdir(parents=True)
    old = time.time() - age_days * 86_400
    os.utime(run, (old, old))
    return run


class CleanupTests(unittest.TestCase):
    def test_a_cheap_run_keeps_only_the_newest(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            newest = _run(root, "tests/output/suites", "1794769213228859901", 30)
            older = _run(root, "tests/output/suites", "1794769213228859900", 30)
            stale = cleanup.superseded([newest, older], set())
        self.assertEqual(stale, [older])

    def test_an_expensive_run_keeps_more_history(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [
                _run(root, "benchmarks/output/koboldcpp", f"17947692132288599{index:02d}", 200) for index in range(6)
            ]
            stale = cleanup.superseded(runs, set())
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0], sorted(runs, key=lambda path: path.name)[0])

    def test_a_cited_run_is_never_superseded(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            newest = _run(root, "tests/output/suites", "1794769213228859901", 30)
            cited = _run(root, "tests/output/suites", "1794769213228859900", 30)
            stale = cleanup.superseded([newest, cited], {cited.name})
        self.assertEqual(stale, [])

    def test_a_recent_run_is_left_alone(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            newest = _run(root, "tests/output/suites", "1794769213228859901", 1)
            recent = _run(root, "tests/output/suites", "1794769213228859900", 1)
            stale = cleanup.superseded([newest, recent], set())
        self.assertEqual(stale, [])

    def test_the_cost_class_follows_the_area(self):
        self.assertTrue(cleanup._expensive(project_cfg.BASE_DIR / "scripts/benchmarks/output/a/b/1"))
        self.assertTrue(cleanup._expensive(project_cfg.BASE_DIR / "scripts/tests/output/probes/a/b/1"))
        self.assertFalse(cleanup._expensive(project_cfg.BASE_DIR / "scripts/tests/output/suites/a/b/1"))

    def test_a_vanished_run_counts_as_stale(self):
        self.assertGreater(cleanup._age_days(Path("nowhere") / "1"), 1000)
