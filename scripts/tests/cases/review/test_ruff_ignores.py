"""Ruff suppression counting."""

import tempfile
import unittest
from pathlib import Path

from scripts.review import ruff_ignores


class RuffIgnores(unittest.TestCase):
    def test_the_report_counts_every_suppression_source(self):
        value = ruff_ignores.report()
        self.assertIsInstance(value["select"], list)
        self.assertEqual(value["total_entries"], len(value["ignore"]) + value["per_file_entries"])

    def test_per_file_entries_are_counted_per_rule(self):
        settings = ruff_ignores.configuration()
        expected = sum(len(rules) for rules in settings["per_file"].values())
        self.assertEqual(settings["per_file_entries"], expected)

    def test_inline_noqa_is_reported_when_present(self):
        with tempfile.TemporaryDirectory() as folder:
            quiet = Path(folder) / "quiet.py"
            loud = Path(folder) / "loud.py"
            quiet.write_text("value = 1\n", encoding="utf-8")
            loud.write_text("value = 1  # noqa: E501\n", encoding="utf-8")
            self.assertEqual([path.name for path in map(Path, ruff_ignores.inline([quiet, loud]))], ["loud.py"])
