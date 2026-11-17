"""A bare Any in a maintained signature fails; the JSON container form and the tests tree are allowed."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.review.checks import bare_any


def sample(source: str) -> Path:
    folder = Path(tempfile.mkdtemp())
    path = folder / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


class BareAnyTests(unittest.TestCase):
    def test_a_bare_parameter_is_reported(self):
        path = sample("def f(value: Any) -> None: ...\n")
        self.assertEqual(len(bare_any.bare_any(path)), 1)

    def test_a_bare_return_is_reported(self):
        path = sample("def f() -> Any: ...\n")
        self.assertEqual(len(bare_any.bare_any(path)), 1)

    def test_a_json_container_is_allowed(self):
        path = sample("def f(value: dict[str, Any]) -> dict[str, Any]: ...\n")
        self.assertEqual(bare_any.bare_any(path), [])

    def test_the_tests_tree_is_exempt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "scripts" / "tests" / "cases" / "sample.py"
            case.parent.mkdir(parents=True)
            case.write_text("def f(value: Any) -> None: ...\n", encoding="utf-8")
            with (
                patch.object(project_cfg, "BASE_DIR", root),
                patch.object(bare_any, "maintained_files", return_value=[case]),
            ):
                self.assertEqual(bare_any.findings(), [])

    def test_a_code_file_under_the_root_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "scripts" / "sample.py"
            case.parent.mkdir(parents=True)
            case.write_text("def f(value: Any) -> None: ...\n", encoding="utf-8")
            with (
                patch.object(project_cfg, "BASE_DIR", root),
                patch.object(bare_any, "maintained_files", return_value=[case]),
            ):
                self.assertEqual(len(bare_any.findings()), 1)


if __name__ == "__main__":
    unittest.main()
