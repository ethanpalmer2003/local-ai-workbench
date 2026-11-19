"""A condition that nests operators too deeply is reported; a call counts as one fact."""

import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.review.checks.expression import MAX_DEPTH, nesting, overlong_conditions


class ExpressionDepthTests(unittest.TestCase):
    def test_a_flat_condition_nests_nothing(self):
        self.assertEqual(nesting(ast.parse("a and b", mode="eval").body), 0)

    def test_a_call_is_one_fact_whatever_it_contains(self):
        self.assertEqual(nesting(ast.parse("any(x or y for x in items)", mode="eval").body), 0)

    def test_a_deeply_nested_condition_is_found(self):
        source = "if a or (b and (c or (d and (e or f)))):\n    pass\n"
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.py"
            path.write_text(source, encoding="utf-8")
            found = overlong_conditions(path)
        self.assertEqual(len(found), 1)
        self.assertGreaterEqual(found[0][2], MAX_DEPTH)

    def test_a_short_condition_passes(self):
        source = "if a and (b or c):\n    pass\n"
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.py"
            path.write_text(source, encoding="utf-8")
            self.assertEqual(overlong_conditions(path), [])
