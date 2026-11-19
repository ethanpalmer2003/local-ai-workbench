"""The tree inventory reads the guard's own list and parses what git and robocopy report."""

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.tools import tree_sizes


class TreeSizeTests(unittest.TestCase):
    def test_guarded_reads_segments_and_tree_paths(self):
        with TemporaryDirectory() as temporary:
            plugin = Path(temporary) / "index.js"
            plugin.write_text(
                "const HEAVY_SEGMENTS = [\n  'data',\n];\nconst HEAVY_TREES = ['scripts/tests/output'];\n",
                encoding="utf-8",
            )
            segments, trees = tree_sizes.guarded(plugin)
        self.assertEqual(segments, {"data"})
        self.assertEqual(trees, {"scripts/tests/output"})

    def test_an_absent_plugin_answers_nothing(self):
        self.assertEqual(tree_sizes.guarded(Path("nowhere") / "index.js"), (set(), set()))

    def test_covered_matches_a_segment_and_a_tree_path(self):
        segments, trees = {"data"}, {"scripts/tests/output"}
        self.assertTrue(tree_sizes.covered(project_cfg.BASE_DIR / "data", segments, trees))
        self.assertTrue(tree_sizes.covered(project_cfg.BASE_DIR / "scripts/tests/output", segments, trees))
        self.assertFalse(tree_sizes.covered(project_cfg.BASE_DIR / "scripts/tools", segments, trees))

    def test_measure_reads_the_robocopy_summary(self):
        summary = "               Files :       2       2       0\n               Bytes :      15      15       0\n"
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout=summary, stderr="")
        with patch.object(tree_sizes.subprocess, "run", return_value=completed):
            self.assertEqual(tree_sizes.measure(project_cfg.BASE_DIR), (2, 15))

    def test_ignored_reads_the_nul_separated_answer(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"data\x00scripts/state\x00", stderr="")
        with patch.object(tree_sizes.subprocess, "run", return_value=completed):
            matched = tree_sizes.ignored([project_cfg.BASE_DIR / "data", project_cfg.BASE_DIR / "scripts/tools"])
        self.assertEqual(matched, {project_cfg.BASE_DIR / "data", project_cfg.BASE_DIR / "scripts/state"})

    def test_no_paths_asks_git_nothing(self):
        self.assertEqual(tree_sizes.ignored([]), set())
