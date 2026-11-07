"""Benchmark preflight checks fail fast, before a backend loads a model."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks.shared import preflight
from scripts.launchers import launch_util
from scripts.tests.shared.paths import CasePaths


class PreflightTests(unittest.TestCase):
    def test_a_missing_input_names_every_absent_file(self):
        with CasePaths(__file__).temporary_directory() as folder:
            present = Path(folder) / "model.gguf"
            present.write_text("x")
            with self.assertRaisesRegex(FileNotFoundError, "server: .*missing.exe"):
                preflight.require_paths({"model": present, "server": Path(folder) / "missing.exe"})

    def test_an_occupied_port_stops_the_run_instead_of_waiting(self):
        with (
            patch.object(launch_util, "port_listening", side_effect=[False, True]),
            self.assertRaisesRegex(RuntimeError, "Ports already in use: audio: 8888"),
        ):
            preflight.require_free_ports({"kobold": 5002, "audio": 8888})

    def test_idle_ports_pass_without_output(self):
        with patch.object(launch_util, "port_listening", return_value=False):
            self.assertIsNone(preflight.require_free_ports({"kobold": 5002}))


if __name__ == "__main__":
    unittest.main()
