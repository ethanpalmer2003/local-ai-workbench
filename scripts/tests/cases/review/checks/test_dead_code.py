"""The dead-code section keeps deletion-shaped findings and drops names something outside reads."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.review.checks import dead_code
from scripts.review.checks.dead_code import findings
from scripts.tests.shared.paths import CasePaths


class FindingTests(unittest.TestCase):
    def test_a_function_and_a_class_with_no_reader_are_reported(self):
        output = (
            "scripts/x.py:4: unused function 'orphan' (60% confidence)\n"
            "scripts/x.py:9: unused class 'Leftover' (60% confidence)\n"
        )
        self.assertEqual(len(findings(output)), 2)

    def test_protocol_attributes_methods_and_variables_are_not_reported(self):
        output = (
            "scripts/x.py:4: unused attribute 'close_connection' (60% confidence)\n"
            "scripts/x.py:8: unused method 'do_GET' (60% confidence)\n"
            "scripts/config/models/ids.py:7: unused variable 'ASR_WHISPERCPP_BASE' (60% confidence)\n"
        )
        self.assertEqual(findings(output), [])

    def test_unreachable_code_is_reported(self):
        output = "scripts/x.py:5: unreachable code after 'return' (100% confidence)\n"
        self.assertEqual(len(findings(output)), 1)


class ScopedSkipTests(unittest.TestCase):
    def verdict(self, before: str, after: str) -> bool:
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "module.py").write_text(after, encoding="utf-8")
            with patch.object(dead_code, "git_text_or_none", return_value=before):
                return dead_code.verdict_cannot_change(["module.py"], root)

    def test_a_body_edit_that_names_the_same_things_cannot_move_the_verdict(self):
        self.assertTrue(self.verdict("def f():\n    return 1\n", "def f():\n    return 2\n"))

    def test_a_removed_call_can_orphan_a_definition(self):
        self.assertFalse(self.verdict("def f():\n    return g()\n", "def f():\n    return 1\n"))

    def test_a_new_import_can_arrive_unused(self):
        self.assertFalse(self.verdict("def f():\n    return 1\n", "import os\n\n\ndef f():\n    return 1\n"))

    def test_missing_upstream_or_an_empty_change_set_runs_the_scan(self):
        self.assertFalse(self.verdict("", "def f():\n    return 1\n"))
        self.assertFalse(dead_code.verdict_cannot_change([]))

    def test_the_scoped_entry_point_skips_and_says_why(self):
        with (
            patch.object(dead_code, "verdict_cannot_change", return_value=True),
            patch.object(dead_code, "main") as run,
        ):
            self.assertEqual(dead_code.scoped(["module.py"]), 0)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
