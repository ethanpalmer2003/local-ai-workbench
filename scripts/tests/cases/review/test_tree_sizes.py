"""The tree listing asks git once, flags an expensive unignored tree and never walks without `--measure`."""

import io
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.review import tree_sizes
from scripts.review.checks import inventory_code


class TreeSizesTests(unittest.TestCase):
    root = project_cfg.BASE_DIR / "harness"

    def _run(self, arguments: list[str], roots: list[Path], ignored: set[Path]) -> tuple[int, str]:
        output = io.StringIO()
        with (
            patch.object(tree_sizes, "_roots", return_value=roots),
            patch.object(tree_sizes, "ignored", return_value=ignored),
            redirect_stdout(output),
        ):
            status = tree_sizes.main(arguments)
        return status, output.getvalue()

    def test_no_paths_asks_git_nothing(self):
        with patch.object(subprocess, "run") as run:
            self.assertEqual(tree_sizes.ignored([]), set())
        run.assert_not_called()

    def test_git_output_maps_back_to_absolute_paths(self):
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"data\x00scripts/state\x00")
        with patch.object(subprocess, "run", return_value=completed):
            found = tree_sizes.ignored([project_cfg.BASE_DIR / "data"])
        self.assertEqual(found, {project_cfg.BASE_DIR / "data", project_cfg.BASE_DIR / "scripts/state"})

    def test_measure_returns_the_inventory_walk(self):
        with patch.object(inventory_code, "tree_totals", return_value=(7, 11)) as totals:
            self.assertEqual(tree_sizes.measure(self.root), (7, 11))
        totals.assert_called_once_with(self.root)

    def test_default_pass_lists_without_measuring(self):
        with patch.object(tree_sizes, "measure") as measure:
            status, output = self._run([], [self.root], set())
        measure.assert_not_called()
        self.assertEqual(status, 0)
        self.assertIn("ignored=False  harness", output)

    def test_a_covered_tree_is_not_flagged(self):
        status, output = self._run(["--measure"], [self.root], {self.root})
        self.assertEqual(status, 0)
        self.assertIn("ignored=True", output)
        self.assertNotIn("[WARN]", output)

    def test_an_expensive_unignored_tree_fails_the_run(self):
        with patch.object(tree_sizes, "measure", return_value=(30_000, 600_000_000)):
            status, output = self._run(["--measure"], [self.root], set())
        self.assertEqual(status, 1)
        self.assertIn("[WARN] harness is expensive and not ignored", output)

    def test_a_small_unignored_tree_passes(self):
        with patch.object(tree_sizes, "measure", return_value=(5, 1_000)):
            status, output = self._run(["--measure"], [self.root], set())
        self.assertEqual(status, 0)
        self.assertIn("0.00 GB", output)


if __name__ == "__main__":
    unittest.main()
