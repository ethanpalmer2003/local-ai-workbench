"""State cleanup removes only old leftovers, and the model cache is pruned one folder at a time."""

import os
import tempfile
import time
import unittest
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


if __name__ == "__main__":
    unittest.main()
