"""Review samples: the module in full, the copied definitions under one header per owner, and the accounting."""

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

    def test_a_missing_function_is_a_refusal(self):
        path = sample_file("owner.py", "VALUE = 1\n")
        try:
            with self.assertRaises(SystemExit):
                sample_code.definition(path, "absent")
        finally:
            path.unlink()

    def test_the_sample_lists_what_it_leaves_out(self):
        module = sample_file(
            "module.py",
            "from scripts.shared.graph import graph, walk\n\n\ndef pick(groups):\n    return walk(graph(), groups)\n",
        )
        try:
            sample = sample_code.build(module, [], "")
        finally:
            module.unlink()
        self.assertIn("left out: graph, walk from scripts.shared.graph", sample)
        self.assertIn("def pick(groups):", sample)

    def test_the_sample_starts_with_the_module_and_ends_with_the_accounting(self):
        module = sample_file("module.py", '"""The rule."""\n\n\ndef pick(groups):\n    return groups\n')
        owner = sample_file("owner.py", "def walk(x):\n    return x\n")
        try:
            sample = sample_code.build(module, [(owner, "walk")], "")
        finally:
            module.unlink()
            owner.unlink()
        self.assertTrue(sample.startswith('"""The rule."""'))
        self.assertNotIn("lines)", sample)
        self.assertTrue(sample.rstrip().splitlines()[-1].startswith("# - copied in: walk from"))

    def test_a_copied_function_is_not_listed_as_left_out(self):
        module = sample_file("module.py", "from scripts.shared.graph import walk\n")
        owner = sample_file("owner.py", "def walk(x):\n    return x\n")
        try:
            sample = sample_code.build(module, [(owner, "walk")], "")
        finally:
            module.unlink()
            owner.unlink()
        self.assertNotIn("left out:", sample)
        self.assertIn("copied from scripts/tests/output/sample-code/owner.py", sample)

    def test_one_owner_gets_one_header(self):
        module = sample_file("module.py", '"""The rule."""\n')
        owner = sample_file("owner.py", "def one(x):\n    return x\n\n\ndef two(x):\n    return x\n")
        try:
            sample = sample_code.build(module, [(owner, "one"), (owner, "two")], "Both halves of the walk.")
        finally:
            module.unlink()
            owner.unlink()
        self.assertEqual(sample.count("# - copied from"), 1)
        self.assertIn("Both halves of the walk.", sample)
        self.assertIn("# - copied in: one, two from", sample)

    def test_a_name_the_copied_code_still_needs_is_listed_with_its_source(self):
        module = sample_file("module.py", '"""The rule."""\n\n\ndef pick():\n    return walk([])\n')
        owner = sample_file(
            "owner.py", "from collections import deque\n\n\ndef walk(items):\n    return deque(items)\n"
        )
        try:
            sample = sample_code.build(module, [(owner, "walk")], "")
        finally:
            module.unlink()
            owner.unlink()
        self.assertIn("# - left out: deque from collections", sample)


if __name__ == "__main__":
    unittest.main()
