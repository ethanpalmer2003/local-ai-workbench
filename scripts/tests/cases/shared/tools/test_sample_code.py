"""Review samples: the module in full, the copied functions labeled, and the imports left out listed."""

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
    def test_a_copied_function_says_where_it_lives(self):
        path = sample_file("owner.py", "def walk(edges, changed):\n    return changed\n")
        try:
            text = sample_code.named_source(path, "walk", "The one-hop walk.")
        finally:
            path.unlink()
        self.assertIn("scripts/tests/output/sample-code/owner.py", text)
        self.assertIn("The one-hop walk.", text)
        self.assertIn("def walk(edges, changed):", text)
        self.assertNotIn("import", text)

    def test_a_copied_constant_comes_with_its_line(self):
        path = sample_file("owner.py", "REACH_DEPTH = 1\nOTHER = 2\n")
        try:
            text = sample_code.named_source(path, "REACH_DEPTH", "One hop.")
        finally:
            path.unlink()
        self.assertIn("REACH_DEPTH = 1", text)
        self.assertNotIn("OTHER", text)

    def test_a_missing_function_is_a_refusal(self):
        path = sample_file("owner.py", "VALUE = 1\n")
        try:
            with self.assertRaises(SystemExit):
                sample_code.named_source(path, "absent", "")
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


if __name__ == "__main__":
    unittest.main()
