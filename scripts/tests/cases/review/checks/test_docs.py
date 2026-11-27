"""Structure checks that read documents: basename casing, root placement and the short-document review list."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.review.checks import docs

BASE = Path(project_cfg.BASE_DIR)


class MarkdownNameTests(unittest.TestCase):
    def test_tool_required_names_and_uppercase_basenames_pass(self):
        for name in ("README.md", "AGENTS.md", "SKILL.md", "CHECKS.md", "CAPABILITIES-NOTES.md"):
            with self.subTest(name=name):
                self.assertEqual(docs.markdown_name_issues(BASE / name), [])

    def test_a_lowercase_basename_is_reported(self):
        issues = docs.markdown_name_issues(BASE / "notes" / "lower-case-notes.md")
        self.assertEqual(len(issues), 1)
        self.assertIn("Markdown basename must be uppercase", issues[0])


class RootDocumentTests(unittest.TestCase):
    def test_readme_and_agents_are_the_only_allowed_root_documents(self):
        for name in ("README.md", "AGENTS.md"):
            with self.subTest(name=name):
                self.assertIn(name, docs.ROOT_MARKDOWN_ALLOWED)

    def test_a_document_outside_the_allowed_pair_is_reported(self):
        stray = BASE / "STRAY.md"
        stray.write_text("# Stray\n\nA document that belongs under notes.\n", encoding="utf-8")
        try:
            issues = docs.root_document_issues()
        finally:
            stray.unlink()
        self.assertEqual(len(issues), 1)
        self.assertIn("STRAY.md", issues[0])

    def test_a_clean_root_reports_nothing(self):
        self.assertEqual(docs.root_document_issues(), [])


class RoleTests(unittest.TestCase):
    def test_lists_are_uncapped_and_prose_keeps_its_cap(self):
        for relative in (
            "notes/TODO.md",
            "notes/OPEN-QUESTIONS.md",
            "notes/OPEN-QUESTIONS-RESOLVED.md",
            "notes/UPSTREAM-INDEX.md",
            "scripts/tests/notes/STATUS-INDEX.md",
            "scripts/tests/notes/OUTCOMES.md",
            ".agents/FAILURES.md",
            ".agents/RESTRICTIONS.md",
        ):
            with self.subTest(relative=relative):
                self.assertIsNone(docs.markdown_budget(relative))
        self.assertEqual(docs.markdown_budget("README.md"), 1000)
        # - an agent rule that is prose still keeps the medium cap
        self.assertEqual(docs.markdown_budget(".agents/CODE.md"), 700)

    def test_known_homes_claim_their_role(self):
        cases = {
            "AGENTS.md": "hub",
            ".agents/skills/docs-writing/SKILL.md": "agent rule",
            ".agents/CHECKS.md": "agent rule",
            ".agents/CODE.md": "agent rule",
            "notes/TODO.md": "running list",
            "notes/reviews/STRUCTURE-REVIEW.md": "review record",
            "notes/ONBOARDING.md": "note",
            "scripts/tests/notes/STATUS-INDEX.md": "running list",
            "scripts/tests/notes/GENERATED-CAPABILITY-MATRIX.md": "generated page",
            "scripts/config/notes/GENERATED-LANGUAGE-MATRIX.md": "generated page",
            "scripts/config/comfyui/TUNING.md": "component guide",
            "scripts/config/comfyui/README.md": "hub",
            "scripts/config/llamacpp/HRX.md": "component guide",
        }
        for relative, role in cases.items():
            with self.subTest(relative=relative):
                self.assertEqual(docs.document_role(relative), role)

    def test_a_running_list_beside_a_component_is_reported(self):
        issues = docs.role_issues([BASE / "scripts/config/TODO.md"])
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("notes root", issues[0])

    def test_a_tuning_document_outside_a_component_is_reported(self):
        issues = docs.role_issues([BASE / "notes/TUNING.md"])
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("component folder", issues[0])

    def test_a_document_with_no_known_role_is_reported(self):
        issues = docs.role_issues([BASE / "docs/UNCLASSIFIED.md"])
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("no document role", issues[0])

    def test_the_prose_roles_carry_a_cap(self):
        cases = {
            "AGENTS.md": 1000,
            "scripts/config/comfyui/README.md": 1000,
            "scripts/tests/notes/GENERATED-CAPABILITY-MATRIX.md": 1400,
            "notes/reviews/STRUCTURE-REVIEW.md": 700,
            "scripts/config/comfyui/TUNING.md": 700,
            ".agents/CHECKS.md": 700,
        }
        for relative, cap in cases.items():
            with self.subTest(relative=relative):
                self.assertEqual(docs.markdown_budget(relative), cap)

    def test_a_policy_number_outside_its_owner_is_reported(self):
        issues = docs.policy_number_issues("notes/OTHER.md", "The gate stays at McCabe 10.")
        self.assertTrue(any("McCabe" in issue for issue in issues), issues)
        self.assertEqual(docs.policy_number_issues(".agents/CODE.md", "McCabe complexity 10"), [])

    def test_documented_caps_match_the_gate(self):
        self.assertEqual(docs.cap_table_issues(), [])


class PointerTests(unittest.TestCase):
    def test_pointers_count_markdown_targets_and_separate_other_links(self):
        folder = project_cfg.TEST_OUTPUT_DIR / "pointer-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        source, target = folder / "SOURCE.md", folder / "TARGET.md"
        source.write_text(
            "# Source\n\n[Target](TARGET.md) and [Target again](TARGET.md) and [web](https://example.com) "
            "and [code](../x.py) and [evidence](../output/thing/REPORT.md).\n",
            encoding="utf-8",
        )
        target.write_text("# Target\n\nNo outgoing links.\n", encoding="utf-8")
        try:
            with patch.object(docs, "tracked_target", return_value=True):
                stats = docs.pointer_stats([source, target])
        finally:
            source.unlink()
            target.unlink()
            folder.rmdir()
        key = target.relative_to(BASE).as_posix()
        self.assertEqual(stats["external"], 1)
        self.assertEqual(stats["other"], 1)
        self.assertEqual(stats["targets"][key], 2)
        self.assertEqual(stats["sources"][source.relative_to(BASE).as_posix()], 3)
        self.assertIn((source.relative_to(BASE).as_posix(), key), stats["duplicates"])
        self.assertEqual(len(stats["untracked"]), 1)
        self.assertIn(source.relative_to(BASE).as_posix(), stats["unlinked"])


class LinkTests(unittest.TestCase):
    def _fixture(self, body: str) -> Path:
        folder = project_cfg.TEST_OUTPUT_DIR / "link-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "LINKED.md"
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_link_into_an_untracked_path_is_reported(self):
        path = self._fixture("# Linked\n\n[Report](../output/run/REPORT.md)\n")
        try:
            issues = docs.markdown_issues(path, path.read_text(encoding="utf-8"))
        finally:
            path.unlink()
            path.parent.rmdir()
        self.assertTrue(any("untracked" in issue for issue in issues), issues)

    def test_a_link_to_a_present_but_untracked_file_is_reported(self):
        # - the file exists for this checkout but a clone has no copy, so the pointer would be dead
        path = self._fixture("# Linked\n\n[Itself](LINKED.md)\n")
        try:
            with patch.object(docs, "tracked_paths", return_value=frozenset()):
                issues = docs.markdown_issues(path, path.read_text(encoding="utf-8"))
        finally:
            path.unlink()
            path.parent.rmdir()
        self.assertTrue(any("untracked" in issue for issue in issues), issues)

    def test_a_tracked_neighbour_link_resolves(self):
        path = self._fixture("# Linked\n\n[Itself](LINKED.md)\n")
        try:
            with patch.object(docs, "tracked_target", return_value=True):
                issues = docs.markdown_issues(path, path.read_text(encoding="utf-8"))
        finally:
            path.unlink()
            path.parent.rmdir()
        self.assertEqual(issues, [])

    def test_link_format_must_be_relative_with_forward_slashes(self):
        cases = {
            "absolute": "[Notes](C:/AI/notes/TODO.md)",
            "rooted": "[Notes](/notes/TODO.md)",
            "backslash": "[Notes](..\\notes/TODO.md)",
            "space": "[Notes](../notes/TO DO.md)",
            "scheme": "[Notes](file:///C:/AI/notes/TODO.md)",
        }
        for name, link in cases.items():
            with self.subTest(name=name):
                path = self._fixture(f"# Linked\n\n{link}\n")
                try:
                    issues = docs.markdown_issues(path, path.read_text(encoding="utf-8"))
                finally:
                    path.unlink()
                    path.parent.rmdir()
                self.assertTrue(issues, name)

    def test_a_documented_module_must_exist(self):
        path = self._fixture("# Linked\n\nRun `python -m scripts.review.gone` first.\n")
        try:
            issues = docs.markdown_issues(path, path.read_text(encoding="utf-8"))
        finally:
            path.unlink()
            path.parent.rmdir()
        self.assertTrue(any("missing module" in issue for issue in issues), issues)

    def test_a_documented_module_that_exists_is_clean(self):
        path = self._fixture("# Linked\n\nRun `python -m scripts.review.checks.docs` first.\n")
        try:
            issues = docs.markdown_issues(path, path.read_text(encoding="utf-8"))
        finally:
            path.unlink()
            path.parent.rmdir()
        self.assertEqual(issues, [])


class ModelNameTests(unittest.TestCase):
    def _fixture(self, text: str) -> Path:
        folder = project_cfg.TEST_OUTPUT_DIR / "model-name-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "NAMED.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_label_in_a_document_is_reported(self):
        label = next(model.label for model in model_cfg.MODELS if len(model.label) >= 6)
        path = self._fixture(f"# Named\n\nRun `{label}` before the check.\n")
        try:
            issues = docs.model_name_issues([path])
        finally:
            path.unlink()
            path.parent.rmdir()
        self.assertEqual(len(issues), 1)
        self.assertIn(label, issues[0])

    def test_a_role_reference_is_clean(self):
        path = self._fixture("# Role\n\nThe whisper.cpp turbo entry in the catalog speaks first.\n")
        try:
            self.assertEqual(docs.model_name_issues([path]), [])
        finally:
            path.unlink()
            path.parent.rmdir()

    def test_catalog_and_dated_evidence_are_skipped(self):
        for relative in ("scripts/config/models/README.md", "notes/reviews/RUN.md", "scripts/tests/notes/OUTCOMES.md"):
            with self.subTest(relative=relative):
                self.assertTrue(docs.model_names_skipped(relative))
        self.assertFalse(docs.model_names_skipped("scripts/launchers/asr/README.md"))


class GeneratedPageTests(unittest.TestCase):
    header = "Generated by `python -m scripts.tools.language_matrix`; do not edit by hand."

    def test_a_named_and_documented_page_passes(self):
        self.assertEqual(
            docs.generated_page_issues("scripts/config/notes/GENERATED-LANGUAGE-MATRIX.md", self.header), []
        )

    def test_a_generated_name_without_the_header_is_reported(self):
        issues = docs.generated_page_issues("scripts/config/notes/GENERATED-LANGUAGE-MATRIX.md", "# Title")
        self.assertIn("name the command", issues[0])

    def test_a_header_on_another_name_is_reported(self):
        issues = docs.generated_page_issues("scripts/config/notes/LANGUAGE-MATRIX.md", self.header)
        self.assertIn("rename it GENERATED-<NAME>.md", issues[0])

    def test_a_header_naming_a_missing_module_is_reported(self):
        text = "Generated by `python -m scripts.nowhere.matrix`; do not edit by hand."
        issues = docs.generated_page_issues("scripts/config/notes/GENERATED-NOWHERE.md", text)
        self.assertIn("not an importable module", issues[0])

    def test_a_command_with_arguments_is_accepted(self):
        text = "Generated by `python -m scripts.review.checks.inventory_code --complexity-debt`; do not edit by hand."
        self.assertEqual(docs.generated_page_issues("scripts/review/GENERATED-DEBT.md", text), [])


class HubSiblingTests(unittest.TestCase):
    def _folder(self) -> Path:
        folder = project_cfg.TEST_OUTPUT_DIR / "hub-sibling-fixture"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _pair(self, hub_text: str) -> tuple[Path, Path]:
        folder = self._folder()
        hub, sibling = folder / "README.md", folder / "SIBLING.md"
        hub.write_text(hub_text, encoding="utf-8")
        sibling.write_text("# Sibling\n", encoding="utf-8")
        return hub, sibling

    def _clean(self, *paths: Path) -> None:
        for path in paths:
            path.unlink()
        paths[0].parent.rmdir()

    def test_a_hub_that_names_its_sibling_passes(self):
        hub, sibling = self._pair("# Hub\n\n[A sibling](SIBLING.md)\n")
        try:
            self.assertEqual(docs.hub_sibling_issues([hub, sibling]), [])
        finally:
            self._clean(hub, sibling)

    def test_a_sibling_link_with_an_anchor_still_names_it(self):
        hub, sibling = self._pair("# Hub\n\n[A sibling](SIBLING.md#usage)\n")
        try:
            self.assertEqual(docs.hub_sibling_issues([hub, sibling]), [])
        finally:
            self._clean(hub, sibling)

    def test_a_sibling_the_hub_omits_is_reported(self):
        hub, sibling = self._pair("# Hub\n\nNothing points at the sibling.\n")
        try:
            issues = docs.hub_sibling_issues([hub, sibling])
        finally:
            self._clean(hub, sibling)
        self.assertEqual(len(issues), 1)
        self.assertIn("SIBLING.md", issues[0])

    def test_a_folder_without_a_hub_is_left_to_its_parent(self):
        folder = self._folder()
        first, second = folder / "FIRST.md", folder / "SECOND.md"
        first.write_text("# First\n", encoding="utf-8")
        second.write_text("# Second\n", encoding="utf-8")
        try:
            self.assertEqual(docs.hub_sibling_issues([first, second]), [])
        finally:
            self._clean(first, second)


class RunningListTests(unittest.TestCase):
    def test_a_regrouped_todo_loses_its_depth_and_its_empty_section_is_named(self):
        text = (
            "# TODO\n\n- intro\n\n## Broken now\nDescription.\n\n- [ ] one ~1 h\n\n"
            "### Stray section\n\n- [ ] two ~1 h\n\n## Empty\nDescription only.\n\n## Next\n\n- [ ] three ~1 h\n"
        )
        issues = docs.running_list_issues("notes/TODO.md", text)
        self.assertTrue(any("Stray section: heading deeper than 2" in issue for issue in issues), issues)
        self.assertTrue(any("Empty: heading has no entries" in issue for issue in issues), issues)

    def test_a_repeated_heading_is_reported(self):
        text = "# TODO\n\n## Same\nDescription.\n\n- [ ] one ~1 h\n\n## Same\nDescription.\n\n- [ ] two ~1 h\n"
        issues = docs.running_list_issues("notes/TODO.md", text)
        self.assertTrue(any("Same: repeated heading" in issue for issue in issues), issues)

    def test_a_prose_section_in_another_running_list_stays_legal(self):
        text = "# Outcomes\n\n## Delivery\nTwo prose lines.\nMore prose, no list entries.\n"
        self.assertEqual(docs.running_list_issues("scripts/tests/notes/OUTCOMES.md", text), [])

    def test_an_unknown_todo_section_is_reported(self):
        text = "# TODO\n\n## Broken now\nDescription.\n\n- [ ] one ~1 h\n\n## Waiting on a release\n- [ ] two\n"
        issues = docs.running_list_issues("notes/TODO.md", text)
        self.assertTrue(any("Waiting on a release: unknown TODO section" in issue for issue in issues), issues)

    def test_a_well_formed_todo_passes(self):
        text = "# TODO\n\n## Broken now\nDescription.\n\n- [ ] one ~1 h\n\n## Unattended\nDescription.\n\n- [ ] two\n"
        self.assertEqual(docs.running_list_issues("notes/TODO.md", text), [])


if __name__ == "__main__":
    unittest.main()
