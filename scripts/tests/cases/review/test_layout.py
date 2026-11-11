"""Layout rules: component ownership, folder naming and documented limits."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.review import layout


class PolicyTests(unittest.TestCase):
    def test_documented_complexity_limit_matches_config(self):
        self.assertEqual(layout.policy_limit_issues(), [])

    def test_a_module_directly_in_scripts_needs_an_owner_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stray = root / "stray.py"
            stray.touch()
            with patch.object(project_cfg, "SCRIPTS_DIR", root):
                self.assertEqual(layout.owner_issues(stray), ["Unexpected script root module: stray.py"])

    def test_the_package_init_is_allowed_at_the_scripts_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            init = root / "__init__.py"
            init.touch()
            with patch.object(project_cfg, "SCRIPTS_DIR", root):
                self.assertEqual(layout.owner_issues(init), [])
