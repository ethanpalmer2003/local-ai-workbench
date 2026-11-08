"""Structure checks that read documents: basename casing and the short-document review list."""

import unittest
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import structure_docs

BASE = Path(project_cfg.BASE_DIR)


class MarkdownNameTests(unittest.TestCase):
    def test_tool_required_names_and_uppercase_basenames_pass(self):
        for name in ("README.md", "AGENTS.md", "SKILL.md", "CHECKS.md", "CAPABILITIES-NOTES.md"):
            with self.subTest(name=name):
                self.assertEqual(structure_docs.markdown_name_issues(BASE / name), [])

    def test_a_lowercase_basename_is_reported(self):
        issues = structure_docs.markdown_name_issues(BASE / "notes" / "lower-case-notes.md")
        self.assertEqual(len(issues), 1)
        self.assertIn("Markdown basename must be uppercase", issues[0])


class ShortDocumentTests(unittest.TestCase):
    def test_only_documents_under_the_threshold_are_listed(self):
        folder = BASE / "scripts/tests/output/short-doc-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        short, long = folder / "SHORT.md", folder / "LONG.md"
        short.write_text("# Short\n\nOne sentence only.\n", encoding="utf-8")
        long.write_text("# Long\n\n" + "word " * 140 + "\n", encoding="utf-8")
        try:
            listed = structure_docs.short_documents([short, long])
        finally:
            short.unlink()
            long.unlink()
            folder.rmdir()
        self.assertEqual([relative for _, relative in listed], ["scripts/tests/output/short-doc-fixture/SHORT.md"])

    def test_review_records_and_the_generated_ledger_are_skipped(self):
        listed = [relative for _, relative in structure_docs.short_documents(_short_candidates())]
        self.assertFalse([relative for relative in listed if relative.startswith("notes/reviews/")])


def _short_candidates() -> list[Path]:
    return [
        BASE / "notes/reviews" / "STRUCTURE-REVIEW.md",
        BASE / "scripts/review" / "COMPLEXITY-DEBT.md",
        BASE / "scripts/AGENTS.md",
    ]


if __name__ == "__main__":
    unittest.main()
