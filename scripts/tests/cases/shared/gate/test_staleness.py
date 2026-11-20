"""One staleness vocabulary: a fingerprint changes only when content does."""

import tempfile
import unittest
from pathlib import Path

from scripts.shared import staleness


class StalenessTests(unittest.TestCase):
    def root(self) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def test_a_fingerprint_survives_a_rewrite_that_changes_nothing(self):
        root = self.root()
        first = root / "a.py"
        first.write_text("value = 1\n", encoding="utf-8")
        before = staleness.fingerprint([first], root)
        first.write_text("value = 1\n", encoding="utf-8")
        self.assertEqual(staleness.fingerprint([first], root), before)

    def test_a_fingerprint_moves_when_content_moves(self):
        root = self.root()
        first = root / "a.py"
        first.write_text("value = 1\n", encoding="utf-8")
        before = staleness.fingerprint([first], root)
        first.write_text("value = 2\n", encoding="utf-8")
        self.assertNotEqual(staleness.fingerprint([first], root), before)

    def test_a_tree_fingerprint_reads_only_the_suffixes_it_is_given_and_counts_extra(self):
        root = self.root()
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (root / "src" / "notes.md").write_text("prose\n", encoding="utf-8")
        python_only = frozenset({".py"})
        empty = frozenset()
        base = staleness.tree_fingerprint(["src"], root, python_only, empty)
        self.assertEqual(base, staleness.tree_fingerprint(["src"], root, python_only, empty))
        self.assertNotEqual(base, staleness.tree_fingerprint(["src"], root, python_only, empty, extra=b"installed"))
        (root / "src" / "notes.md").write_text("different prose\n", encoding="utf-8")
        self.assertEqual(staleness.tree_fingerprint(["src"], root, python_only, empty), base)

    def test_a_manifest_reports_changed_and_new_files(self):
        root = self.root()
        first, second = root / "a.py", root / "b.py"
        first.write_text("1", encoding="utf-8")
        recorded = staleness.manifest([first], root)
        first.write_text("2", encoding="utf-8")
        second.write_text("3", encoding="utf-8")
        self.assertEqual(staleness.changed_since(recorded, staleness.manifest([first, second], root)), ["a.py", "b.py"])

    def test_a_stamp_matches_only_itself_and_an_empty_stamp_never_matches(self):
        self.assertTrue(staleness.matched("abc", "abc"))
        self.assertFalse(staleness.matched("abc", "abc2"))
        self.assertFalse(staleness.matched("", ""))
        self.assertFalse(staleness.matched(None, "abc"))


if __name__ == "__main__":
    unittest.main()
