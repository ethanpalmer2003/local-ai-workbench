"""The gate's entry point: a clean tree short-circuits unless a flag asked for every section."""

import unittest
from unittest.mock import patch

from scripts.review import __main__ as gate


class GateEntryTests(unittest.TestCase):
    def test_a_clean_tree_checks_nothing(self):
        with (
            patch.object(gate, "changed_since_upstream", return_value=[]),
            patch.object(gate, "full_gate") as full,
            patch.object(gate, "touched_gate") as touched,
        ):
            self.assertEqual(gate.main([]), 0)
        full.assert_not_called()
        touched.assert_not_called()

    def test_a_clean_tree_still_runs_every_section_when_all_was_asked_for(self):
        with (
            patch.object(gate, "changed_since_upstream", return_value=[]),
            patch.object(gate, "full_gate", return_value=0) as full,
        ):
            self.assertEqual(gate.main(["--all"]), 0)
        full.assert_called_once()

    def test_an_unpushed_change_scopes_the_gate_to_it(self):
        with (
            patch.object(gate, "changed_since_upstream", return_value=["scripts/shared/changes.py"]),
            patch.object(gate, "touched_gate", return_value=0) as touched,
            patch.object(gate, "full_gate") as full,
        ):
            self.assertEqual(gate.main([]), 0)
        touched.assert_called_once()
        full.assert_not_called()


if __name__ == "__main__":
    unittest.main()
