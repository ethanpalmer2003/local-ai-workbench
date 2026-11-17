"""Dynamic module loading: each loader form is reported, and a static import is not."""

import unittest
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review.checks import dynamic_imports
from scripts.tests.shared.paths import CasePaths


class DynamicImportTests(unittest.TestCase):
    def load(self, source: str) -> list[str]:
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text(source, encoding="utf-8")
            return dynamic_imports.issues(path)

    def test_a_module_loaded_by_name_is_reported_with_its_line(self):
        found = self.load("import importlib\nimportlib.import_module('scripts.tools.a')\n")
        self.assertEqual(found, ["sample.py:2: dynamic import (importlib.import_module)"])

    def test_every_loader_form_is_named(self):
        source = (
            "import importlib.util\n"
            "import runpy\n"
            "runpy.run_path('tool.py')\n"
            "importlib.util.spec_from_file_location('n', 'tool.py')\n"
            "__import__('scripts.tools.a')\n"
        )
        self.assertEqual(
            [issue.split(": ", 1)[1] for issue in self.load(source)],
            [
                "dynamic import (runpy.run_path)",
                "dynamic import (importlib.util.spec_from_file_location)",
                "dynamic import (__import__)",
            ],
        )

    def test_a_static_import_and_a_string_naming_a_module_are_not_reported(self):
        self.assertEqual(self.load("import scripts.tools.a\nNAME = 'scripts.tools.a'\n"), [])

    def test_an_unparsable_file_reports_nothing(self):
        self.assertEqual(self.load("def broken(:\n"), [])

    def test_every_exemption_names_a_file_that_exists(self):
        for relative in dynamic_imports.ALLOWED:
            with self.subTest(path=relative):
                self.assertTrue((project_cfg.BASE_DIR / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
