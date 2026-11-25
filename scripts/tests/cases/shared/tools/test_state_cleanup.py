"""State cleanup removes only old leftovers, and the model cache is pruned one folder at a time."""

import os
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from scripts.tools import state_cleanup


class StateCleanupTests(unittest.TestCase):
    def root(self) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    @staticmethod
    def age(path: Path, days: float) -> None:
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))

    def test_only_entries_older_than_the_cutoff_are_pruned(self):
        root = self.root()
        old, new = root / "_MEI1", root / "_MEI2"
        old.mkdir()
        new.mkdir()
        (old / "payload.bin").write_bytes(b"x")
        self.age(old, 8)
        count, freed = state_cleanup.prune("_MEI*", root, time.time() - 7 * 86400, False)
        self.assertEqual(count, 1)
        self.assertGreater(freed, 0)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_path_size_counts_a_file_and_a_tree_and_survives_a_missing_path(self):
        root = self.root()
        (root / "one.bin").write_bytes(b"x" * 4)
        nested = root / "tree" / "deeper"
        nested.mkdir(parents=True)
        (nested / "two.bin").write_bytes(b"y" * 6)
        self.assertEqual(state_cleanup.path_size(root / "one.bin"), 4)
        self.assertEqual(state_cleanup.path_size(root / "tree"), 6)
        self.assertEqual(state_cleanup.path_size(root / "absent"), 0)

    def test_a_dry_run_reports_without_removing(self):
        root = self.root()
        folder = root / "_MEI3"
        folder.mkdir()
        self.age(folder, 8)
        count, _ = state_cleanup.prune("_MEI*", root, time.time() - 7 * 86400, True)
        self.assertEqual(count, 1)
        self.assertTrue(folder.exists())

    def test_the_model_cache_prunes_direct_children_only(self):
        cache = self.root() / "audiocpp-gguf" / "abc"
        cache.mkdir(parents=True)
        blob = cache / "model.bin"
        blob.write_bytes(b"x")
        self.age(blob, 40)
        count, _ = state_cleanup.prune("*", cache, time.time() - 30 * 86400, False, recursive=False)
        self.assertEqual(count, 1)
        self.assertFalse(blob.exists())
        self.assertTrue(cache.is_dir())

    def test_gate_reports_keep_the_latest_two(self):
        root = self.root()
        generated = root / "generated"
        reports = generated / "code_review"
        reports.mkdir(parents=True)
        for name in ("1", "2", "3"):
            (reports / name).mkdir()
        with unittest.mock.patch.object(state_cleanup.project_cfg, "component") as component:
            component.return_value.generated_dir = generated
            count, _ = state_cleanup.prune_review_reports(False)
        self.assertEqual(count, 1)
        self.assertEqual(sorted(item.name for item in reports.iterdir()), ["2", "3"])

    def test_launch_scratch_keeps_in_extractions_and_new_entries(self):
        root = self.root()
        old, new, extraction = root / "old", root / "new", root / "_MEI9"
        for folder in (old, new, extraction):
            folder.mkdir()
            (folder / "payload.bin").write_bytes(b"x")
        self.age(old, 9)
        self.age(extraction, 9)
        with unittest.mock.patch.object(state_cleanup.cfg.LAUNCH, "temp_dir", root):
            count, _ = state_cleanup.prune_launch_cache(time.time() - 7 * 86400, False)
        self.assertEqual(count, 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertTrue(extraction.exists())

    def test_extractions_keep_the_newest_few_whatever_their_age(self):
        root = self.root()
        created = []
        for index in range(5):
            folder = root / f"_MEI{index}"
            folder.mkdir()
            (folder / "payload.bin").write_bytes(b"x")
            created.append(folder)
        count, _ = state_cleanup.prune_extractions(root, False, keep=2, min_age_hours=0)
        self.assertEqual(count, 3)
        remaining = sorted(item.name for item in root.iterdir())
        self.assertEqual(remaining, ["_MEI3", "_MEI4"])

    def test_a_young_extraction_is_never_pruned(self):
        # - a running child owns its extraction, so the count bound cannot reach it
        root = self.root()
        for index in range(4):
            (root / f"_MEI{index}").mkdir()
        count, _ = state_cleanup.prune_extractions(root, False, keep=1)
        self.assertEqual(count, 0)
        self.assertEqual(len(list(root.iterdir())), 4)

    def _suite_case(self, root: Path, runs: int) -> Path:
        """The layout a suite writes: runs/<suite>/<case>/unreviewed/<date>/<epoch>/{artifacts,logs,temp}."""
        case = root / "temp" / "runs" / "suites" / "frameworks_smoke" / "unreviewed" / "2026-11-24"
        for index in range(runs):
            run = case / str(1795578000000000000 + index)
            (run / "artifacts").mkdir(parents=True)
            (run / "artifacts" / "report.json").write_text("{}", encoding="utf-8")
            (run / "logs").mkdir()
            (run / "temp").mkdir()
        return case

    def test_suite_runs_keep_the_newest_few_per_case_whatever_their_age(self):
        root = self.root()
        case = self._suite_case(root, 6)
        with unittest.mock.patch.object(state_cleanup.project_cfg, "STATE_DIR", root):
            count, _ = state_cleanup._prune_suite_runs(False)
        self.assertEqual(count, 3)
        kept = sorted(item.name for item in case.iterdir())
        self.assertEqual(kept, [str(1795578000000000000 + index) for index in (3, 4, 5)])

    def test_stray_scratch_files_leave_but_their_folders_stay(self):
        root = self.root()
        temp = root / "temp"
        (temp / "runs").mkdir(parents=True)
        old, new = temp / "probe.py", temp / "fresh.py"
        for path in (old, new):
            path.write_text("print()", encoding="utf-8")
        self.age(old, 9)
        with unittest.mock.patch.object(state_cleanup.project_cfg, "STATE_DIR", root):
            count, _ = state_cleanup.prune_scratch_files(time.time() - 7 * 86400, False)
        self.assertEqual(count, 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertTrue((temp / "runs").is_dir())


if __name__ == "__main__":
    unittest.main()
