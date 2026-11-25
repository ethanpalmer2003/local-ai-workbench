"""The entry-point census stays complete: a new main() must be classified to land."""

import importlib
import unittest

from scripts.config import project_config as project_cfg
from scripts.review.lists import entry_points


def _importable(module: str) -> str:
    """The import that carries main(): scripts.review runs as its __main__ module."""
    return "scripts.review.__main__" if module == "scripts.review" else module


class EntryPointTests(unittest.TestCase):
    def test_every_main_is_registered_and_nothing_registered_is_gone(self):
        self.assertEqual(set(entry_points.discovered()), set(entry_points.ALL))

    def test_every_entry_imports_with_a_main(self):
        for module in entry_points.ALL:
            with self.subTest(module=module):
                imported = importlib.import_module(_importable(module))
                self.assertTrue(callable(getattr(imported, "main", None)))

    def test_kinds_stay_inside_the_vocabulary(self):
        for module, kind in entry_points.ALL.items():
            with self.subTest(module=module):
                self.assertIn(kind, entry_points.KINDS)

    def test_the_report_names_every_registered_module(self):
        text = entry_points.report()
        for module in entry_points.ALL:
            self.assertIn(module, text)

    def test_the_reporters_page_is_current(self):
        page = project_cfg.BASE_DIR / "scripts/review/lists/GENERATED-REPORTERS.md"
        self.assertEqual(page.read_text(encoding="utf-8"), entry_points.reporters_page())


if __name__ == "__main__":
    unittest.main()
