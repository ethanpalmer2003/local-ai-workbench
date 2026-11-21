"""An installed weight must be re-fetchable or byte-pinned: a link, or a sha256 of its bytes."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.review.checks import model_references


def installed(url: str | None, sha256: str | None, present: bool = True) -> SimpleNamespace:
    return SimpleNamespace(label="fixture/model", url=url, sha256=sha256, path=Mock(is_file=lambda: present))


class ModelProvenanceTests(unittest.TestCase):
    def test_an_installed_model_with_neither_link_nor_hash_is_a_gap(self):
        issues = model_references.provenance_issues({"fixture/model": installed(None, None)})
        self.assertEqual(issues, ["Installed model has neither a source link nor a sha256: fixture/model"])

    def test_a_hash_alone_covers_a_hand_downloaded_weight(self):
        self.assertEqual(model_references.provenance_issues({"fixture/model": installed(None, "abc")}), [])

    def test_a_link_alone_is_enough(self):
        self.assertEqual(
            model_references.provenance_issues({"fixture/model": installed("https://example.test/m.gguf", None)}), []
        )

    def test_an_absent_model_is_not_checked(self):
        self.assertEqual(
            model_references.provenance_issues({"fixture/model": installed(None, None, present=False)}), []
        )


if __name__ == "__main__":
    unittest.main()
