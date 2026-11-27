"""The restriction list prints from its owners, so the table is never restated in code."""

import contextlib
import io
import unittest
from pathlib import Path

from scripts.review import restrictions
from scripts.tests.shared.paths import CasePaths


class RestrictionTableTests(unittest.TestCase):
    def test_the_separator_row_is_formatting_rather_than_a_rule(self):
        self.assertTrue(restrictions.is_separator(["---", ":--", "---"]))
        self.assertFalse(restrictions.is_separator(["Restriction", "Enforced by"]))
        self.assertFalse(restrictions.is_separator([]))

    def test_two_tables_in_one_document_stay_apart(self):
        with CasePaths(__file__).temporary_directory() as folder:
            page = Path(folder) / "RULES.md"
            page.write_text(
                "# Rules\n\n| Rule | Owner |\n| --- | --- |\n| one | a |\n| two | b |\n\n"
                "prose between them\n\n| Symptom | Fix |\n| --- | --- |\n| three | c |\n",
                encoding="utf-8",
            )
            tables = restrictions.tables(page)
        self.assertEqual([row[0] for row in tables[0]], ["Rule", "one", "two"])
        self.assertEqual([row[0] for row in tables[1]], ["Symptom", "three"])


class RestrictionResolveTests(unittest.TestCase):
    def test_a_relative_link_becomes_the_path_it_points_at(self):
        self.assertEqual(
            restrictions.resolve("[failed step](FAILURES.md)", Path(".agents")), "failed step (.agents/FAILURES.md)"
        )

    def test_a_link_above_the_owner_resolves_from_the_repository_root(self):
        text = restrictions.resolve("[layout](../scripts/review/checks/layout.py)", Path(".agents"))
        self.assertEqual(text, "layout (scripts/review/checks/layout.py)")

    def test_an_external_link_keeps_its_url(self):
        text = restrictions.resolve("[docs](https://example.com/x)", Path(".agents"))
        self.assertEqual(text, "docs https://example.com/x")


class RestrictionCommandTests(unittest.TestCase):
    def test_every_row_of_the_owner_is_printed_once(self):
        rows = restrictions.tables(restrictions.project_cfg.BASE_DIR / restrictions.RESTRICTIONS)[0][1:]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            status = restrictions.main([])
        printed = out.getvalue()
        self.assertEqual(status, 0)
        self.assertIn(f"[OK] {len(rows)} restrictions printed", printed)
        # - the profile plugin is installed on this machine and untracked, so it is cited as a plain path
        self.assertIn("runs/state/plugins/guard-deep-scan", printed)
        self.assertIn("installed in the profile, not tracked", printed)

    def test_all_adds_the_failure_rows_and_the_harness_rules(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            status = restrictions.main(["--all"])
        printed = out.getvalue()
        self.assertEqual(status, 0)
        self.assertIn(f"### Failures ({restrictions.FAILURES.as_posix()})", printed)
        self.assertIn(f"### Harness rules ({restrictions.HARNESS.as_posix()})", printed)
        # - the numbering continues across the three owners rather than restarting
        self.assertNotIn("\n 1. Every `pwsh` call", printed)
