"""Config text resolves the repository root, and a config that is not an object fails where it is named."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.config import paths
from scripts.config import project_config as project_cfg


class ConfigPathTests(unittest.TestCase):
    def test_a_placeholder_resolves_to_the_repository_root(self):
        text = paths.resolve_text('{"path": "{AI_ROOT}/data"}')
        self.assertEqual(text, f'{{"path": "{project_cfg.BASE_DIR.as_posix()}/data"}}')

    def test_a_json_object_loads_with_its_placeholder_resolved(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "server.json"
            path.write_text('{"root": "{AI_ROOT}"}', encoding="utf-8")
            self.assertEqual(paths.load_json(path), {"root": project_cfg.BASE_DIR.as_posix()})

    def test_a_json_array_is_refused_where_the_file_is_named(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "server.json"
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must hold a JSON object"):
                paths.load_json(path)


if __name__ == "__main__":
    unittest.main()
