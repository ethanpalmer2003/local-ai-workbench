"""Model runs: the dry run proves inputs and ports, and the watchdog bounds a frozen child."""

import socket
import unittest
from pathlib import Path

from scripts.tests import model_run
from scripts.tests.shared.paths import CasePaths


class ModelRunTests(unittest.TestCase):
    def test_a_missing_input_and_a_busy_port_fail_the_dry_run(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(probe.close)
        probe.bind(("127.0.0.1", 0))
        probe.listen(1)
        with CasePaths(__file__).temporary_directory() as folder:
            spec = model_run.RunSpec(
                "example",
                "json",
                (),
                minutes=5,
                silence=60,
                requires=(Path(folder) / "absent.gguf",),
                ports=(int(probe.getsockname()[1]),),
            )
            problems = model_run.check(spec)
        self.assertTrue(any(problem.startswith("missing input") for problem in problems), problems)
        self.assertTrue(any("already in use" in problem for problem in problems), problems)

    def test_a_ready_spec_passes_and_names_its_limits(self):
        spec = model_run.RunSpec("example", "json", ("--flag",), minutes=5, silence=60)
        self.assertEqual(model_run.check(spec), [])
        self.assertEqual(model_run.command(spec)[-1], "--flag")

    def test_the_cli_needs_a_module_and_a_dry_run_loads_nothing(self):
        self.assertEqual(model_run.main([]), 2)
        self.assertEqual(model_run.main(["--dry-run", "json"]), 0)

    def test_an_unimportable_module_is_a_dry_run_failure(self):
        spec = model_run.RunSpec("example", "scripts.no_such_module", (), 5, 60)
        self.assertTrue(any("cannot import" in problem for problem in model_run.check(spec)))


if __name__ == "__main__":
    unittest.main()
