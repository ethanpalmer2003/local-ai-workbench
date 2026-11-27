"""A tracked config is copied only when something actually has to be resolved."""

import tempfile
import unittest
from pathlib import Path

from scripts.config import paths


class MaterializeTests(unittest.TestCase):
    def test_a_config_without_a_placeholder_is_handed_over_as_is(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "plain.json"
            source.write_text('{"port": 1}\n', encoding="utf-8")
            self.assertEqual(paths.materialize(source), source)

    def test_a_placeholder_earns_a_resolved_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "with-root.json"
            source.write_text('{"path": "{AI_ROOT}/data"}\n', encoding="utf-8")
            target = paths.materialize(source, folder="paths-test")
            self.assertNotEqual(target, source)
            self.assertIn(paths.project_cfg.BASE_DIR.as_posix(), target.read_text(encoding="utf-8"))
            self.assertNotIn("{AI_ROOT}", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
