"""Walrus operators: one inside a comprehension is reported, and the loop and guard headers stay allowed."""

import unittest
from pathlib import Path

from scripts.review.checks import walrus
from scripts.tests.shared.paths import CasePaths


class WalrusTests(unittest.TestCase):
    def load(self, source: str) -> list[str]:
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text(source, encoding="utf-8")
            return walrus.issues(path)

    def messages(self, source: str) -> list[str]:
        return [issue.split(": ", 1)[1] for issue in self.load(source)]

    def test_a_walrus_inside_a_comprehension_is_reported_with_its_name(self):
        self.assertEqual(
            self.messages("found = [item for item in items if (item := look(item))]\n"),
            ["walrus inside a comprehension (item)"],
        )

    def test_every_comprehension_shape_is_covered(self):
        source = (
            "seen = {name for path in paths if (name := module(path))}\n"
            "mapped = {key: value for key in keys if (value := read(key))}\n"
            "stream = (row for row in rows if (row := parse(row)))\n"
        )
        self.assertEqual(
            self.messages(source),
            [
                "walrus inside a comprehension (name)",
                "walrus inside a comprehension (value)",
                "walrus inside a comprehension (row)",
            ],
        )

    def test_a_loop_header_and_a_guard_stay_allowed(self):
        source = "while chunk := response.read(1024):\n    use(chunk)\n\n\nif found := look():\n    use(found)\n"
        self.assertEqual(self.load(source), [])

    def test_a_comprehension_without_a_walrus_is_not_reported(self):
        self.assertEqual(self.load("found = [item for item in items if item]\n"), [])

    def test_the_census_names_the_shapes_the_rule_allows(self):
        source = "while chunk := read():\n    use(chunk)\n\n\nif found := look():\n    use(found)\n"
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text(source, encoding="utf-8")
            counts = walrus.contexts([path])
        self.assertEqual(counts["while header"], 1)
        self.assertEqual(counts["if header"], 1)
        self.assertEqual(counts[walrus.BANNED], 0)

    def test_an_unparsable_file_reports_nothing(self):
        self.assertEqual(self.load("def broken(:\n"), [])


if __name__ == "__main__":
    unittest.main()
