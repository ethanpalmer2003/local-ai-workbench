"""Verbatim duplicate blocks: the pylint report parses into file pairs, and only growth fails."""

import unittest
from collections import Counter

from scripts.review import duplicates


class DuplicateReportTests(unittest.TestCase):
    modules = {"scripts.a": "scripts/a.py", "scripts.b": "scripts/b.py", "scripts.c": "scripts/c.py"}

    def test_a_report_becomes_one_count_per_file_pair(self):
        text = (
            "************* Module scripts.a\n"
            "scripts/a.py:1:0: R0801: Similar lines in 2 files\n"
            "==scripts.a:[10:14]\n"
            "==scripts.b:[40:44]\n"
            "                    import os\n"
            "scripts/a.py:30:0: R0801: Similar lines in 3 files\n"
            "==scripts.a:[70:74]\n"
            "==scripts.b:[80:84]\n"
            "==scripts.c:[90:94]\n"
        )
        counts = duplicates.parse(text, self.modules)
        self.assertEqual(counts["scripts/a.py|scripts/b.py"], 2)
        self.assertEqual(counts["scripts/a.py|scripts/c.py"], 1)
        self.assertEqual(counts["scripts/b.py|scripts/c.py"], 1)

    def test_three_files_report_counts_every_pair_once(self):
        text = (
            "scripts/a.py:1:0: R0801: Similar lines in 3 files\n"
            "==scripts.a:[1:4]\n"
            "==scripts.b:[1:4]\n"
            "==scripts.c:[1:4]\n"
        )
        counts = duplicates.parse(text, self.modules)
        self.assertEqual(sum(counts.values()), 3)

    def test_only_new_pairs_or_growth_are_unreviewed(self):
        counts = Counter({"scripts/a.py|scripts/b.py": 2, "scripts/a.py|scripts/c.py": 1})
        baseline = {"scripts/a.py|scripts/b.py": 2, "scripts/x.py|scripts/y.py": 1}
        self.assertEqual(duplicates.unreviewed(counts, baseline), [("scripts/a.py|scripts/c.py", 1, 0)])

    def test_a_grown_pair_is_unreviewed(self):
        counts = Counter({"scripts/a.py|scripts/b.py": 3})
        self.assertEqual(
            duplicates.unreviewed(counts, {"scripts/a.py|scripts/b.py": 2}), [("scripts/a.py|scripts/b.py", 3, 2)]
        )


if __name__ == "__main__":
    unittest.main()
