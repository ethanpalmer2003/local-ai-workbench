"""The cleanup keeps what a decision cites and weights history by how expensive a run was."""

import os
import time
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.config import project_config as project_cfg
from scripts.config import trash as trash_config
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
            newest = _run(root, "runs/tests/suites", "1794769213228859901", 30)
            older = _run(root, "runs/tests/suites", "1794769213228859900", 30)
            stale = cleanup.superseded([newest, older], set())
        self.assertEqual(stale, [older])

    def test_an_expensive_run_keeps_more_history(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [_run(root, "runs/benchmarks/koboldcpp", f"17947692132288599{index:02d}", 200) for index in range(6)]
            stale = cleanup.superseded(runs, set())
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0], sorted(runs, key=lambda path: path.name)[0])

    def test_a_cited_run_is_never_superseded(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            newest = _run(root, "runs/tests/suites", "1794769213228859901", 30)
            cited = _run(root, "runs/tests/suites", "1794769213228859900", 30)
            stale = cleanup.superseded([newest, cited], {cited.name})
        self.assertEqual(stale, [])

    def test_a_recent_run_is_left_alone(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            newest = _run(root, "runs/tests/suites", "1794769213228859901", 1)
            recent = _run(root, "runs/tests/suites", "1794769213228859900", 1)
            stale = cleanup.superseded([newest, recent], set())
        self.assertEqual(stale, [])

    def test_the_cost_class_follows_the_area(self):
        self.assertTrue(cleanup._expensive(project_cfg.BASE_DIR / "runs/benchmarks/a/b/1"))
        self.assertTrue(cleanup._expensive(project_cfg.BASE_DIR / "runs/tests/probes/a/b/1"))
        self.assertFalse(cleanup._expensive(project_cfg.BASE_DIR / "runs/tests/suites/a/b/1"))

    def test_a_vanished_run_counts_as_stale(self):
        self.assertGreater(cleanup._age_days(Path("nowhere") / "1"), 1000)

    def test_a_read_only_file_inside_a_trash_day_does_not_stop_the_emptying(self):
        with TemporaryDirectory() as temporary:
            trash = Path(temporary) / "trash"
            stale = trash / "2020-01-01" / "cleanup" / ".git" / "objects"
            stale.mkdir(parents=True)
            blocked = stale / "read-only-object"
            blocked.write_text("object", encoding="utf-8")
            os.chmod(blocked, 0o444)
            with unittest.mock.patch.object(trash_config, "trash_root", return_value=trash):
                self.assertEqual(cleanup.empty_trash(1), 1)
            self.assertFalse((trash / "2020-01-01").exists())

    def test_a_run_the_age_rule_and_the_area_cap_both_name_is_listed_once(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [
                _run(root, "runs/tests/suites", f"17947692132288599{index:02d}", 30)
                for index in range(cleanup.MAX_RUNS_PER_AREA + 2)
            ]
            stale = cleanup.superseded(runs, set())
        self.assertEqual(len(stale), len(set(stale)))
        self.assertEqual(len(stale), cleanup.MAX_RUNS_PER_AREA + 1)

    def test_the_keep_override_reaches_the_run_rule(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [_run(root, "runs/tests/suites", f"17947692132288599{index:02d}", 30) for index in range(4)]
            kept = cleanup.superseded(runs, set(), keep=3, older_days=7)
        self.assertEqual(len(kept), 1)
