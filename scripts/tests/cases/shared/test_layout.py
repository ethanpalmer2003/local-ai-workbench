"""Layout rules: component ownership, folder naming and documented limits."""

import unittest

from scripts.review import layout


class PolicyTests(unittest.TestCase):
    def test_documented_complexity_limit_matches_config(self):
        self.assertEqual(layout.policy_limit_issues(), [])
