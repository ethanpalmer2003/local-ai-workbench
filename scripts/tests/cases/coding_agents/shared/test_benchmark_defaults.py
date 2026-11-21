"""Parked clients and stacks stay out of every default arm; only a named request runs them."""

import unittest

from scripts.benchmarks.coding_agents.shared import benchmark_agents
from scripts.benchmarks.shared import framework_compare


class ParkedDefaultsTests(unittest.TestCase):
    def test_coding_benchmark_runs_pi_by_default_but_keeps_the_others_nameable(self):
        self.assertEqual(benchmark_agents.DEFAULT_CLIENTS, ("pi",))
        self.assertEqual(set(benchmark_agents.CLIENTS), {"pi", "littlecoder", "ohmypi", "nanocoder"})
        parser = benchmark_agents._build_parser()
        self.assertEqual(parser.parse_args([]).clients, ["pi"])
        self.assertEqual(parser.parse_args(["--clients", "nanocoder"]).clients, ["nanocoder"])

    def test_framework_compare_keeps_the_parked_lemonade_stack_out_of_its_default(self):
        self.assertNotIn("lemonade", framework_compare.DEFAULT_BACKENDS)
        self.assertIn("lemonade", framework_compare.BACKENDS)
        self.assertLessEqual(set(framework_compare.DEFAULT_BACKENDS), set(framework_compare.BACKENDS))
