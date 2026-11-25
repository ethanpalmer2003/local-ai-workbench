"""The console-output rule: one line per print, or a table through render_table."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.review import output_lines


class OutputLines(unittest.TestCase):
    def _issues(self, source: str) -> list[str]:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text(source, encoding="utf-8")
            return output_lines.issues(path)

    def test_two_content_lines_in_one_print_are_flagged(self):
        found = self._issues('print("Local commit: base\\nUpstream commit: upstream")\n')
        self.assertEqual(len(found), 1)
        self.assertIn("2 lines", found[0])

    def test_a_leading_blank_line_is_a_separator(self):
        self.assertEqual(self._issues('print("\\n=== SECTION ===")\n'), [])

    def test_a_single_line_and_a_table_call_are_allowed(self):
        self.assertEqual(self._issues('print("done")\nprint(render_table(rows, columns))\n'), [])

    def test_an_f_string_with_two_content_lines_is_flagged(self):
        found = self._issues('print(f"a: {one}\\nb: {two}")\n')
        self.assertEqual(len(found), 1)

    def test_the_census_counts_prints_by_content_lines(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text('print("one")\nprint(render_table(rows, columns))\n', encoding="utf-8")
            counts = output_lines.census([path])
        self.assertEqual(counts[1], 1)
        self.assertEqual(counts[0], 1)
