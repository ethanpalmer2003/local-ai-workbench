"""Capability modules run under a category budget, and a hung one is killed at its deadline."""

import sys
import time
import unittest

from scripts.tests.shared.model_free import fixture_processes
from scripts.tools import probe_runner


class ProbeRunnerTests(unittest.TestCase):
    @fixture_processes()
    def test_a_hung_command_is_killed_at_the_deadline(self):
        started = time.perf_counter()
        status = probe_runner.run([sys.executable, "-c", "import time; time.sleep(30)"], 0.2)
        self.assertEqual(status, probe_runner.TIMEOUT_STATUS)
        self.assertLess(time.perf_counter() - started, 10)

    @fixture_processes()
    def test_a_quick_command_passes_its_own_status(self):
        self.assertEqual(probe_runner.run([sys.executable, "-c", "print('ok')"], 10), 0)

    def test_each_category_has_its_own_budget(self):
        self.assertEqual(probe_runner.category_for("scripts.benchmarks.llamacpp.benchmark_specspeed"), "smoke")
        self.assertEqual(probe_runner.category_for("scripts.benchmarks.llamacpp.benchmark_ngram"), "benchmark")
        self.assertEqual(probe_runner.category_for("scripts.anything.else"), "probe")
        self.assertLess(probe_runner.CATEGORY_SECONDS["smoke"], probe_runner.CATEGORY_SECONDS["benchmark"])


if __name__ == "__main__":
    unittest.main()
