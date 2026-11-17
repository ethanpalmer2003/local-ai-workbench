"""Line length accepts string content and flags code; the limits page shows every rule and its edge."""

import tempfile
import unittest
from pathlib import Path

from scripts.review import limits
from scripts.review.checks import line_length


def sample(source: str) -> Path:
    """A scratch module holding the source, for the checks that take a path list."""
    folder = Path(tempfile.mkdtemp())
    path = folder / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


class LineLengthTests(unittest.TestCase):
    def test_a_wrappable_code_line_is_reported(self):
        path = sample("result = " + " + ".join(["alpha"] * 30) + "\n")
        self.assertEqual(len(line_length.findings([path])), 1)

    def test_a_long_string_literal_is_accepted(self):
        path = sample('PROMPT = "' + "x" * 200 + '"\n')
        self.assertEqual(line_length.findings([path]), [])
        self.assertEqual(line_length.literals([path]), 1)

    def test_a_template_line_is_accepted(self):
        path = sample('PAGE = """\n' + "<div>" * 40 + '\n"""\n')
        self.assertEqual(line_length.findings([path]), [])
        self.assertEqual(line_length.literals([path]), 1)

    def test_a_short_file_reports_nothing(self):
        self.assertEqual(line_length.findings([sample("value = 1\n")]), [])


class LimitsReportTests(unittest.TestCase):
    def test_the_page_names_every_rule_and_its_limit(self):
        text = "\n".join(limits.report())
        for rule in ("line length", "annotations", "folders", "file length", "owned tokens", "duplicates"):
            self.assertIn(rule, text)
        self.assertIn(f"{line_length.LIMIT} characters", text)

    def test_the_borderline_list_matches_the_annotation_check(self):
        expected = {str(item) for item in limits.borderline_annotations()}
        reported = {line[2:] for line in limits.report() if line.startswith("- ") and " scores " in line}
        self.assertEqual(expected, reported)


if __name__ == "__main__":
    unittest.main()
