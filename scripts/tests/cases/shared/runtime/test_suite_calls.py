"""One table of how many model requests each live target makes at one repeat."""

import unittest

from scripts.tests.cases.suites import live_frameworks, quick_validation
from scripts.tests.shared import suite_calls


class SuiteCallTests(unittest.TestCase):
    def test_every_backend_probe_declares_its_calls(self):
        self.assertEqual(set(suite_calls.BACKEND_CALLS), set(quick_validation.PROBES))

    def test_every_launcher_target_declares_or_explains_its_calls(self):
        self.assertEqual(
            set(suite_calls.LAUNCHER_CALLS) | set(suite_calls.STREAMED), set(live_frameworks.LAUNCHER_TARGETS)
        )
        self.assertTrue(set(live_frameworks.LAUNCHER_TARGETS) >= suite_calls.STREAMED)

    def test_a_declared_count_is_a_positive_number(self):
        for counts in (suite_calls.BACKEND_CALLS, suite_calls.LAUNCHER_CALLS):
            for name, count in counts.items():
                with self.subTest(name=name):
                    self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()
