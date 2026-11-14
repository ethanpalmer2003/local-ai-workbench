"""The dead-code check reports unreferenced names and leaves every real reference alone."""

import tempfile
import unittest
from pathlib import Path

from scripts.review.unused import dead_definitions


class DeadCodeTests(unittest.TestCase):
    def _dead(self, sources: dict[str, str]) -> set[str]:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = []
            for name, text in sources.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(path)
            return {item.name for item in dead_definitions(files)}

    def test_a_name_nothing_mentions_is_dead(self):
        dead = self._dead({"owner.py": "def orphan():\n    return 1\n\nUNUSED = 2\n"})
        self.assertEqual(dead, {"orphan", "UNUSED"})

    def test_a_call_or_a_patch_target_counts_as_a_reference(self):
        dead = self._dead(
            {
                "owner.py": "def used():\n    return 1\n\ndef patched():\n    return 2\n",
                "caller.py": "from owner import used\n\nused()\npatch.object(owner, 'patched')\n",
            }
        )
        self.assertEqual(dead, set())

    def test_a_name_mentioned_in_a_string_still_counts(self):
        dead = self._dead({"owner.py": "def documented():\n    return 1\n\nNOTE = 'documented above'\n"})
        self.assertEqual(dead, {"NOTE"})

    def test_a_nested_name_belongs_to_its_parent(self):
        dead = self._dead({"outer.py": "def outer():\n    def inner():\n        return 1\n\n    return inner()\n"})
        self.assertEqual(dead, {"outer"})
