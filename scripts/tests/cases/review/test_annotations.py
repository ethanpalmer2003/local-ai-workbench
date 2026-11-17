"""Annotation complexity: a nested type scores, deduplicates per function, and fails above the cap."""

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.review.checks import annotations


def write(root: Path, name: str, source: str) -> Path:
    path = root / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def parameter(source: str) -> ast.expr | None:
    """The annotation on the first parameter of a one-function source."""
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node.args.args[0].annotation


class ScoreTests(unittest.TestCase):
    def test_a_flat_type_scores_one(self):
        self.assertEqual(annotations.score(parameter("def f(x: int) -> None: ...")), (1, 0, 0))

    def test_nesting_adds_depth_and_atoms(self):
        self.assertEqual(annotations.score(parameter("def f(x: dict[str, list[int]]) -> None: ...")), (4, 2, 0))

    def test_a_union_reports_its_width(self):
        self.assertEqual(annotations.score(parameter("def f(x: int | str | None) -> None: ...")), (3, 0, 3))


class FindingsTests(unittest.TestCase):
    def _findings(self, source: str) -> list[annotations.Annotation]:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = write(root, "sample.py", source)
            return annotations.findings([path])

    def test_the_five_part_tuple_is_reported_and_a_named_record_is_not(self):
        heavy = self._findings(
            """
            def f(rows: dict[int, list[tuple[int | None, str, bool | None, set[tuple[str, int]], bool]]]) -> None: ...
            """
        )
        self.assertEqual(len(heavy), 1)
        self.assertGreater(heavy[0].score, annotations.MAX_SCORE)
        light = self._findings(
            """
            def f(rows: dict[int, list[Remaining]]) -> None: ...
            """
        )
        self.assertEqual(light, [])

    def test_one_function_with_two_heavy_parameters_is_one_finding(self):
        rows = self._findings(
            """
            def f(first: dict[int, list[tuple[str, bool, set[tuple[str, int]]]]],
                  second: dict[int, list[tuple[str, bool, set[tuple[str, int]]]]]) -> None: ...
            """
        )
        self.assertEqual(len(rows), 1)

    def test_a_clean_file_reports_nothing(self):
        self.assertEqual(self._findings("def f(value: int) -> int:\n    return value\n"), [])

    def test_a_deep_chain_is_flagged_below_the_score_cap(self):
        rows = self._findings("def f(value: dict[str, dict[str, dict[str, dict[str, int]]]]) -> None: ...")
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0].depth, annotations.MAX_DEPTH)


if __name__ == "__main__":
    unittest.main()
