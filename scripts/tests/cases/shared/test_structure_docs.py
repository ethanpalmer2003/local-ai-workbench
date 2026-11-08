"""Structure checks that read documents: basename casing, root placement and the short-document review list."""

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


class RootDocumentTests(unittest.TestCase):
    def test_readme_and_agents_are_the_only_allowed_root_documents(self):
        for name in ("README.md", "AGENTS.md"):
            with self.subTest(name=name):
                self.assertIn(name, structure_docs.ROOT_MARKDOWN_ALLOWED)

    def test_a_document_outside_the_allowed_pair_is_reported(self):
        stray = BASE / "STRAY.md"
        stray.write_text("# Stray\n\nA document that belongs under notes.\n", encoding="utf-8")
        try:
            issues = structure_docs.root_document_issues()
        finally:
            stray.unlink()
        self.assertEqual(len(issues), 1)
        self.assertIn("STRAY.md", issues[0])

    def test_a_clean_root_reports_nothing(self):
        self.assertEqual(structure_docs.root_document_issues(), [])


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


class WordCountTests(unittest.TestCase):
    def test_a_document_over_its_budget_is_marked_over(self):
        self.assertEqual(structure_docs.word_marker(600, 500, "notes/BIG.md", BASE / "notes/BIG.md"), "over")

    def test_a_document_under_the_floor_is_marked_short(self):
        self.assertEqual(structure_docs.word_marker(50, 500, "notes/SMALL.md", BASE / "notes/SMALL.md"), "short")

    def test_exempt_documents_are_not_marked_short(self):
        for name in ("README.md", "AGENTS.md", "SKILL.md"):
            with self.subTest(name=name):
                self.assertEqual(structure_docs.word_marker(10, 500, name, BASE / name), "")
        review = "notes/reviews/STRUCTURE-REVIEW.md"
        self.assertEqual(structure_docs.word_marker(10, 500, review, BASE / review), "")

    def test_rows_are_ordered_by_word_count(self):
        folder = BASE / "scripts/tests/output/word-row-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        small, big = folder / "SMALL.md", folder / "BIG.md"
        small.write_text("# Small\n\nshort\n", encoding="utf-8")
        big.write_text("# Big\n\n" + "word " * 40 + "\n", encoding="utf-8")
        try:
            rows = structure_docs.word_rows([small, big])
        finally:
            small.unlink()
            big.unlink()
            folder.rmdir()
        self.assertEqual(
            [row[2] for row in rows], [big.relative_to(BASE).as_posix(), small.relative_to(BASE).as_posix()]
        )
        self.assertEqual(rows[0][3], "short")
        self.assertEqual(rows[1][3], "short")


def _short_candidates() -> list[Path]:
    return [
        BASE / "notes/reviews" / "STRUCTURE-REVIEW.md",
        BASE / "scripts/review" / "COMPLEXITY-DEBT.md",
        BASE / "scripts/AGENTS.md",
    ]


if __name__ == "__main__":
    unittest.main()
