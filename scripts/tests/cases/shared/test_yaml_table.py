"""The YAML table printer keeps record order, derives column order, and refuses anything but a list."""

import tempfile
import unittest
from pathlib import Path

from scripts.tools import yaml_table

SAMPLE = """
- thing: first
  kind: model
- thing: second
  extra: added
"""


class YamlTableTests(unittest.TestCase):
    def path(self, text: str) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "records.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_columns_follow_the_order_the_records_introduce_them(self):
        entries = yaml_table.read(self.path(SAMPLE))
        self.assertEqual(yaml_table.columns(entries), ["thing", "kind", "extra"])

    def test_a_requested_column_list_replaces_the_derived_one(self):
        entries = yaml_table.read(self.path(SAMPLE))
        self.assertEqual(yaml_table.columns(entries, ["extra", "thing"]), ["extra", "thing"])

    def test_render_keeps_row_order_and_prints_every_value(self):
        text = yaml_table.render(yaml_table.read(self.path(SAMPLE)))
        self.assertLess(text.index("first"), text.index("second"))
        self.assertIn("model", text)
        self.assertIn("added", text)

    def test_a_mapping_instead_of_a_list_is_refused(self):
        with self.assertRaises(ValueError):
            yaml_table.read(self.path("thing: first\n"))


if __name__ == "__main__":
    unittest.main()
