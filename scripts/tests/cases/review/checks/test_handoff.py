"""The handoff bundle ranks the files that ask for judgment and leaves the mechanical findings out."""

import ast
import json
import unittest
import unittest.mock
from pathlib import Path

from scripts.review import handoff
from scripts.tests.shared.paths import CasePaths


def handler(source: str) -> ast.ExceptHandler:
    tree = ast.parse(source)
    return next(node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler))


class HandlerTests(unittest.TestCase):
    def test_a_handler_that_does_nothing_is_silent(self):
        for source in (
            "try:\n    f()\nexcept Exception:\n    pass\n",
            "try:\n    f()\nexcept Exception:\n    return None\n",
            "try:\n    f()\nexcept Exception:\n    return False\n",
            "try:\n    f()\nexcept Exception:\n    continue\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(handoff.silent_except(handler(source)))

    def test_a_handler_that_raises_logs_or_returns_a_value_is_not_silent(self):
        for source in (
            "try:\n    f()\nexcept Exception:\n    raise\n",
            "try:\n    f()\nexcept Exception:\n    print('failed')\n",
            "try:\n    f()\nexcept Exception:\n    return 0\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(handoff.silent_except(handler(source)))

    def test_a_broad_handler_catches_everything(self):
        self.assertTrue(handoff.broad_except(handler("try:\n    f()\nexcept:\n    pass\n")))
        self.assertTrue(handoff.broad_except(handler("try:\n    f()\nexcept Exception:\n    pass\n")))
        self.assertFalse(handoff.broad_except(handler("try:\n    f()\nexcept OSError:\n    pass\n")))


class BundleTests(unittest.TestCase):
    def test_a_file_record_carries_the_call_shapes_and_the_smells(self):
        source = (
            '"""Module."""\n\n\n'
            "def documented(value: int) -> str:\n"
            '    """Say it."""\n'
            "    return str(value)\n\n\n"
            "def undocumented(value):\n"
            "    try:\n        return int(value)\n"
            "    except Exception:\n        pass\n"
        )
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "scripts" / "pkg").mkdir(parents=True)
            path = root / "scripts" / "pkg" / "module.py"
            path.write_text(source, encoding="utf-8")
            record = handoff.file_record(path, root)
        self.assertEqual(record["path"], "scripts/pkg/module.py")
        self.assertEqual([item["name"] for item in record["functions"]], ["documented", "undocumented"])
        self.assertEqual(record["functions"][0]["signature"], "(value: int) -> str")
        self.assertEqual(record["undocumented"], [record["functions"][1]["line"]])
        self.assertEqual(len(record["silent_excepts"]), 1)
        self.assertEqual(len(record["broad_excepts"]), 1)

    def test_the_brief_names_the_heavy_files_and_leaves_the_gate_alone(self):
        records: list[handoff.FileRecord] = [
            {
                "path": "scripts/heavy.py",
                "lines": 400,
                "functions": [{"name": "run", "line": 1, "span": 90, "signature": "() -> None", "documented": True}],
                "classes": [],
                "silent_excepts": [10, 20],
                "broad_excepts": [30],
                "undocumented": [],
            },
            {
                "path": "scripts/calm.py",
                "lines": 20,
                "functions": [],
                "classes": [],
                "silent_excepts": [],
                "broad_excepts": [],
                "undocumented": [],
            },
        ]
        text = "\n".join(handoff.brief(records, ranked=1))
        self.assertIn("| scripts/heavy.py | 400 | 1 | 2 | 1 | 1 |", text)
        self.assertNotIn("scripts/calm.py", text)
        self.assertIn("Do not spend judgment on them", text)

    def test_a_run_writes_the_brief_and_the_index(self):
        record = {
            "path": "scripts/pkg/module.py",
            "lines": 3,
            "functions": [],
            "classes": [],
            "silent_excepts": [],
            "broad_excepts": [],
            "undocumented": [],
        }
        with CasePaths(__file__).temporary_directory() as folder:
            destination = Path(folder) / "bundle"
            with unittest.mock.patch.object(handoff, "index", return_value=[record]):
                self.assertEqual(handoff.main(["--out", str(destination)]), 0)
            self.assertTrue((destination / "HANDOFF.md").is_file())
            index = json.loads((destination / "ast_map.json").read_text(encoding="utf-8"))
        self.assertEqual(index["files"][0]["path"], "scripts/pkg/module.py")
