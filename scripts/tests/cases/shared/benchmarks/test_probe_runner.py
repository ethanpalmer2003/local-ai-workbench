"""The probe runner kills a hung command at its deadline instead of waiting it out."""

import sys
import time
import unittest

from scripts.tools import probe_runner


class ProbeRunnerTests(unittest.TestCase):
    def test_a_hung_command_is_killed_at_the_deadline(self):
        started = time.perf_counter()
        status = probe_runner.run([sys.executable, "-c", "import time; time.sleep(30)"], 0.2)
        self.assertEqual(status, probe_runner.TIMEOUT_STATUS)
        self.assertLess(time.perf_counter() - started, 10)

    def test_a_quick_command_passes_its_own_status(self):
        self.assertEqual(probe_runner.run([sys.executable, "-c", "print('ok')"], 10), 0)

    def test_budgets_are_named_per_probe(self):
        self.assertEqual(probe_runner.budget_for("scripts.benchmarks.llamacpp.benchmark_ngram"), 300)
        self.assertEqual(probe_runner.budget_for("scripts.anything.else"), probe_runner.DEFAULT_BUDGET)


if __name__ == "__main__":
    unittest.main()
