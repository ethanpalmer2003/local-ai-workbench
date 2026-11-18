"""Review samples: the module in full, the copied definitions under one header per owner, and the accounting."""

import ast
import unittest
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.tools import sample_code

BASE = Path(project_cfg.BASE_DIR)


def sample_file(name: str, source: str) -> Path:
    folder = BASE / "scripts/tests/output/sample-code"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(source, encoding="utf-8")
    return path


class SampleCodeTests(unittest.TestCase):
    def test_a_copied_function_is_its_own_source(self):
        path = sample_file("owner.py", "import os\n\n\ndef walk(edges, changed):\n    return changed\n")
        try:
            text = sample_code.definition(path, "walk")
        finally:
            path.unlink()
        self.assertEqual(text, "def walk(edges, changed):\n    return changed")

    def test_a_copied_constant_comes_with_its_line(self):
        path = sample_file("owner.py", "REACH_DEPTH = 1\nOTHER = 2\n")
        try:
            text = sample_code.definition(path, "REACH_DEPTH")
        finally:
            path.unlink()
        self.assertEqual(text, "REACH_DEPTH = 1")

    def test_a_title_leads_the_file_as_a_comment(self):
        module = sample_file("module.py", '"""The rule."""\n')
        try:
            untitled = sample_code.build(module, [])
            titled = sample_code.build(module, [], "One hop back")
        finally:
            module.unlink()
        self.assertTrue(titled.startswith("# One hop back\n\n"))
        self.assertEqual(ast.dump(ast.parse(titled)), ast.dump(ast.parse(untitled)))

    def test_a_missing_function_is_a_refusal(self):
        path = sample_file("owner.py", "VALUE = 1\n")
        try:
            with self.assertRaises(SystemExit):
                sample_code.definition(path, "absent")
        finally:
            path.unlink()

    def test_the_sample_starts_with_the_module_and_ends_with_the_copied_definition(self):
        module = sample_file("module.py", '"""The rule."""\n\n\ndef pick(groups):\n    return groups\n')
        owner = sample_file("owner.py", "def walk(x):\n    return x\n")
        try:
            sample = sample_code.build(module, [(owner, "walk")])
        finally:
            module.unlink()
            owner.unlink()
        self.assertTrue(sample.startswith('"""The rule."""'))
        self.assertNotIn("lines)", sample)
        self.assertIn("# - walk lives in", sample)
        self.assertTrue(sample.rstrip().endswith("return x"))

    def test_one_owner_gets_one_header(self):
        module = sample_file("module.py", '"""The rule."""\n')
        owner = sample_file("owner.py", "def one(x):\n    return x\n\n\ndef two(x):\n    return x\n")
        try:
            sample = sample_code.build(module, [(owner, "one"), (owner, "two")])
        finally:
            module.unlink()
            owner.unlink()
        self.assertEqual(sample.count("# - one, two lives in"), 1)
        self.assertIn("# - one, two lives in", sample)


if __name__ == "__main__":
    unittest.main()
