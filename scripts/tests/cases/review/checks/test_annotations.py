"""Annotation complexity: a nested type scores, deduplicates per function, and fails above the cap."""

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.config import project_config as project_cfg
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


class DefaultTests(unittest.TestCase):
    def findings(self, source: str) -> list[tuple[str, int, str]]:
        directory = Path(project_cfg.BASE_DIR) / "scripts/tests/output/annotation-defaults"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "sample.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        try:
            return annotations.default_findings([path])
        finally:
            path.unlink()

    def test_a_mutable_default_is_refused(self):
        self.assertIn("is a mutable default", self.findings("def f(values=[]): ...")[0][2])
        self.assertIn("is a mutable default", self.findings("def f(values=set()): ...")[0][2])

    def test_a_call_in_a_default_is_refused(self):
        self.assertIn("calls Path()", self.findings("def f(where=Path('.')): ...")[0][2])

    def test_a_settings_read_is_refused_and_a_class_constant_is_not(self):
        self.assertIn("reads cfg.SETTINGS", self.findings("def f(settings=cfg.SETTINGS): ...")[0][2])
        self.assertEqual(self.findings("def f(kind=cfg.Kind.MEMBER): ..."), [])

    def test_literals_names_hooks_and_table_lookups_are_allowed(self):
        source = """
            def f(count=1, name=None, hook=lambda: None, pair=(1, 2), empty=frozenset(), size=16000 * 2):
                ...
            def g(profile=PROFILES['small'], mode=Mode.FAST):
                ...
        """
        self.assertEqual(self.findings(source), [])

    def test_each_default_has_one_category(self):
        source = """
            def f(argv=None, limit=None, carried=None):
                if limit is None:
                    limit = 3
            def g(a=1, b=NAME, c=(1, 2), d=lambda: None, e=cfg.KIND, f2=Mode.FAST, h=TABLE['k'], i=16000 * 2):
                ...
            def j(k=frozenset()):
                ...
        """
        tree = ast.parse(textwrap.dedent(source))
        kinds = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        self.assertEqual(sorted(kinds), ["f", "g", "j"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text(textwrap.dedent(source), encoding="utf-8")
            parsed = ast.parse(path.read_text(encoding="utf-8"))
        found = {}
        for node in ast.walk(parsed):
            if not isinstance(node, ast.FunctionDef):
                continue
            for argument, default in annotations._parameters(node):
                found[argument.arg] = annotations.default_kind(argument, default, node)
        self.assertEqual(found["argv"], "argv")
        self.assertEqual(found["limit"], "derived")
        self.assertEqual(found["carried"], "carried")
        self.assertEqual(found["a"], "literal")
        self.assertEqual(found["b"], "name")
        self.assertEqual(found["c"], "tuple")
        self.assertEqual(found["d"], "lambda")
        self.assertEqual(found["e"], "config")
        self.assertEqual(found["f2"], "attribute")
        self.assertEqual(found["h"], "table")
        self.assertEqual(found["i"], "arithmetic")
        self.assertEqual(found["k"], "immutable")

    def test_the_census_counts_every_category(self):
        source = "def f(a=1, b=None, c=[]): ...\n"
        directory = Path(project_cfg.BASE_DIR) / "scripts/tests/output/annotation-census"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "sample.py"
        path.write_text(source, encoding="utf-8")
        try:
            self.assertEqual(annotations.default_census([path]), {"literal": 1, "carried": 1, "mutable": 1})
        finally:
            path.unlink()


class FindingsTests(unittest.TestCase):
    def test_the_future_import_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stale = write(root, "stale.py", "from __future__ import annotations\n\nVALUE = 1\n")
            clean = write(root, "clean.py", "VALUE = 1\n")
            self.assertEqual(annotations.future_imports([stale, clean]), [stale])

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
