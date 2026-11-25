"""The manual-gate inventory finds every live use; the report is computed, never written down."""

import unittest

from scripts.config import project_config as project_cfg
from scripts.review.lists import manual_gates


class ManualGateInventoryTests(unittest.TestCase):
    def test_both_guarded_entry_points_call_the_guard(self):
        guards = {use.file for use in manual_gates.usages() if use.kind == "guard"}
        self.assertEqual(guards, {"scripts/review/__main__.py", "scripts/tests/run.py"})

    def test_passthroughs_hand_the_flag_onward(self):
        files = {use.file for use in manual_gates.usages() if use.kind == "passthrough"}
        for expected in ("scripts/review/__main__.py", "scripts/review/check_repo.bat", "scripts/tests/validate.py"):
            self.assertIn(expected, files)

    def test_the_definition_is_owned_once(self):
        definitions = [use for use in manual_gates.usages() if use.kind == "definition"]
        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].file, "scripts/shared/consent.py")

    def test_every_reported_file_exists(self):
        for use in manual_gates.usages():
            self.assertTrue((project_cfg.BASE_DIR / use.file).is_file(), use.file)


if __name__ == "__main__":
    unittest.main()
