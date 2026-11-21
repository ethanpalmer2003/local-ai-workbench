"""An installed weight must be re-fetchable or byte-pinned: a link, or a sha256 of its bytes."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.config import project_config as project_cfg
from scripts.review.checks import model_references
from scripts.tests.shared.paths import CasePaths


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


class ModelLinkTests(unittest.TestCase):
    def test_a_model_file_link_in_consumer_code_is_reported(self):
        with CasePaths(__file__).temporary_directory() as folder:
            scripts = Path(folder)
            (scripts / "launchers").mkdir()
            (scripts / "launchers" / "example.py").write_text(
                'URL = "https://huggingface.co/org/repo/resolve/main/model.gguf"\n', encoding="utf-8"
            )
            with patch.object(project_cfg, "SCRIPTS_DIR", scripts):
                issues = model_references.link_issues()
        self.assertEqual(len(issues), 1)
        self.assertIn("example.py:1", issues[0])

    def test_a_doc_string_and_an_external_page_are_not_model_links(self):
        with CasePaths(__file__).temporary_directory() as folder:
            scripts = Path(folder)
            (scripts / "tools").mkdir()
            (scripts / "tools" / "example.py").write_text(
                'PAGE = "https://huggingface.co/org/repo"\nDOC = "https://example.test/resolve/main/x.gguf"\n',
                encoding="utf-8",
            )
            with patch.object(project_cfg, "SCRIPTS_DIR", scripts):
                self.assertEqual(model_references.link_issues(), [])


if __name__ == "__main__":
    unittest.main()
