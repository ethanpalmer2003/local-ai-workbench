"""Documentation duplicate check: chunking, filtering and finding shape; no model is started."""

import tempfile
import unittest
from pathlib import Path

from scripts.review import similarity


class SimilarityUnitTests(unittest.TestCase):
    def _units(self, text: str) -> list[dict[str, object]]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doc.md"
            path.write_text(text, encoding="utf-8")
            return similarity.units(path, "doc.md")

    def test_a_bullet_is_one_unit_and_a_heading_becomes_its_path(self):
        found = self._units("# Title\n\n## Section\n\n- The launcher runs without the overlay and still starts.\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["heading"], "Title / Section")
        self.assertEqual(found[0]["kind"], "bullet")

    def test_code_fences_and_tables_are_not_units(self):
        text = "# T\n\n```\n- short code line\n```\n\n| a | b |\n| --- | --- |\n| one | two |\n"
        self.assertEqual(self._units(text), [])

    def test_procedural_boilerplate_is_dropped(self):
        text = "# T\n\n- Approved execution: AppContainer false, administrator false.\n"
        self.assertEqual(self._units(text), [])

    def test_short_lines_are_dropped(self):
        self.assertEqual(self._units("# T\n\n- It stays off.\n"), [])

    def test_prose_is_split_into_sentences(self):
        text = (
            "# T\n\nThe launcher keeps every service starting without the overlay. "
            "A clone without it still starts every service that matters.\n"
        )
        self.assertEqual(len(self._units(text)), 2)


class SimilarityFindingTests(unittest.TestCase):
    def _units(self) -> list[dict[str, object]]:
        return [
            {"doc": "a.md", "heading": "A", "text": "alpha unit one carrying enough words", "kind": "bullet"},
            {"doc": "a.md", "heading": "A", "text": "alpha unit two carrying enough words", "kind": "bullet"},
            {"doc": "b.md", "heading": "B", "text": "beta unit one carrying enough words", "kind": "bullet"},
            {"doc": "b.md", "heading": "B", "text": "beta unit two carrying enough words", "kind": "bullet"},
        ]

    def test_two_matching_units_make_a_finding(self):
        found = similarity.findings([(0.95, 0, 2), (0.93, 1, 3)], self._units())
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["matches"], 2)

    def test_one_short_sentence_is_not_a_finding(self):
        self.assertEqual(similarity.findings([(0.95, 0, 2)], self._units()), [])

    def test_one_long_unit_is_a_finding(self):
        units = self._units()
        units[0]["text"] = "alpha " * 30
        units[2]["text"] = "beta " * 30
        self.assertEqual(len(similarity.findings([(0.95, 0, 2)], units)), 1)


class SimilarityCodeTests(unittest.TestCase):
    def _functions(self, source: str) -> list[dict[str, object]]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "module.py"
            path.write_text(source, encoding="utf-8")
            return similarity.functions(path, "module.py")

    def test_a_function_is_one_unit_and_a_stub_is_skipped(self):
        source = "def long_one(value):\n    total = sun = value + 1\n    return total + sun\n\ndef stub():\n    pass\n"
        found = self._functions(source)
        self.assertEqual([unit["heading"] for unit in found], ["long_one"])
        self.assertEqual(found[0]["doc"], "module.py")

    def test_an_unparsable_module_yields_nothing(self):
        self.assertEqual(self._functions("def broken(:\n"), [])

    def test_code_findings_do_not_need_two_matching_units(self):
        units = [
            {"doc": "a.py", "heading": "one", "text": "def one(): return 1", "kind": "function"},
            {"doc": "b.py", "heading": "two", "text": "def two(): return 1", "kind": "function"},
        ]
        self.assertEqual(similarity.findings([(0.97, 0, 1)], units, require_two=False)[0]["best"], 0.97)
        self.assertEqual(similarity.findings([(0.97, 0, 1)], units), [])


class SimilaritySourceTests(unittest.TestCase):
    def test_a_changed_or_new_document_is_reported(self):
        previous = {"a.md": "one", "b.md": "two", "gone.md": "three"}
        current = {"a.md": "one", "b.md": "changed", "c.md": "four"}
        self.assertEqual(similarity.changed_sources(previous, current), ["b.md", "c.md"])

    def test_an_unchanged_tree_reports_nothing(self):
        self.assertEqual(similarity.changed_sources({"a.md": "one"}, {"a.md": "one"}), [])


if __name__ == "__main__":
    unittest.main()
