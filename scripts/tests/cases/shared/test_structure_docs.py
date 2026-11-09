"""Structure checks that read documents: basename casing, root placement and the short-document review list."""

import unittest
from pathlib import Path

from scripts.config import models as model_cfg
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


class RoleTests(unittest.TestCase):
    def test_known_homes_claim_their_role(self):
        cases = {
            "AGENTS.md": "root",
            ".agents/skills/docs-writing/SKILL.md": "agent rule",
            ".agents/CHECKS.md": "agent rule",
            "notes/TODO.md": "note",
            "notes/reviews/STRUCTURE-REVIEW.md": "review record",
            "notes/ONBOARDING.md": "note",
            "scripts/tests/notes/STATUS.md": "component guide",
            "scripts/config/comfyui/TUNING.md": "component guide",
            "scripts/config/comfyui/README.md": "hub",
            "scripts/config/llamacpp/HRX.md": "component guide",
        }
        for relative, role in cases.items():
            with self.subTest(relative=relative):
                self.assertEqual(structure_docs.document_role(relative), role)

    def test_a_running_list_beside_a_component_is_reported(self):
        issues = structure_docs.role_issues([BASE / "scripts/config/TODO.md"])
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("notes root", issues[0])

    def test_a_tuning_document_outside_a_component_is_reported(self):
        issues = structure_docs.role_issues([BASE / "notes/TUNING.md"])
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("component folder", issues[0])

    def test_a_document_with_no_known_role_is_reported(self):
        issues = structure_docs.role_issues([BASE / "docs/UNCLASSIFIED.md"])
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("no document role", issues[0])

    def test_three_caps_are_assigned_by_role(self):
        cases = {
            "AGENTS.md": 700,
            "scripts/config/comfyui/README.md": 700,
            "notes/TODO.md": 500,
            "notes/reviews/STRUCTURE-REVIEW.md": 500,
            "scripts/config/comfyui/TUNING.md": 500,
            ".agents/CHECKS.md": 300,
        }
        for relative, cap in cases.items():
            with self.subTest(relative=relative):
                self.assertEqual(structure_docs.markdown_budget(relative), cap)


class PointerTests(unittest.TestCase):
    def test_pointers_count_markdown_targets_and_separate_other_links(self):
        folder = BASE / "scripts/tests/output/pointer-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        source, target = folder / "SOURCE.md", folder / "TARGET.md"
        source.write_text(
            "# Source\n\n[Target](TARGET.md) and [web](https://example.com) and [code](../x.py).\n", encoding="utf-8"
        )
        target.write_text("# Target\n\nNo outgoing links.\n", encoding="utf-8")
        try:
            stats = structure_docs.pointer_stats([source, target])
        finally:
            source.unlink()
            target.unlink()
            folder.rmdir()
        key = target.relative_to(BASE).as_posix()
        self.assertEqual(stats["external"], 1)
        self.assertEqual(stats["other"], 1)
        self.assertEqual(stats["targets"][key], 1)
        self.assertEqual(stats["sources"][source.relative_to(BASE).as_posix()], 1)
        self.assertIn(source.relative_to(BASE).as_posix(), stats["unlinked"])


class ModelNameTests(unittest.TestCase):
    def _fixture(self, text: str) -> Path:
        folder = BASE / "scripts/tests/output/model-name-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "NAMED.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_label_in_a_document_is_reported(self):
        label = next(model.label for model in model_cfg.MODELS if len(model.label) >= 6)
        path = self._fixture(f"# Named\n\nRun `{label}` before the check.\n")
        try:
            issues = structure_docs.model_name_issues([path])
        finally:
            path.unlink()
            path.parent.rmdir()
        self.assertEqual(len(issues), 1)
        self.assertIn(label, issues[0])

    def test_a_role_reference_is_clean(self):
        path = self._fixture("# Role\n\nThe whisper.cpp turbo entry in the catalog speaks first.\n")
        try:
            self.assertEqual(structure_docs.model_name_issues([path]), [])
        finally:
            path.unlink()
            path.parent.rmdir()

    def test_catalog_and_dated_evidence_are_skipped(self):
        for relative in ("scripts/config/models/README.md", "notes/reviews/RUN.md", "scripts/tests/notes/OUTCOMES.md"):
            with self.subTest(relative=relative):
                self.assertTrue(structure_docs.model_names_skipped(relative))
        self.assertFalse(structure_docs.model_names_skipped("scripts/launchers/asr/README.md"))


if __name__ == "__main__":
    unittest.main()
