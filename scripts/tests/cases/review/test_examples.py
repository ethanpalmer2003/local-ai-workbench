"""The examples page covers every check the review README names, and its templates still exist."""

import re
import unittest

from scripts.config import project_config as project_cfg

REVIEW = project_cfg.SCRIPTS_DIR / "review"
CHECKS_DIR = REVIEW / "checks"

# - row name -> module that emits the quoted template, or None when the message belongs to a tool
CHECKS: dict[str, str | None] = {
    "annotations": "annotations",
    "line_length": "line_length",
    "bare_any": "bare_any",
    "layout": "layout",
    "owned_tokens": "owned_tokens",
    "duplicates": "duplicates",
    "docs": "docs",
    "ruff": None,
    "basedpyright": None,
    "model_references": None,
    "frontend_wiring": "frontend_wiring",
    "inventory_code": "inventory_code",
    "typography": "typography",
    "comments": "comments",
    "spellings": "spellings",
    "dead_code": None,
    "package_audit": None,
    "network_timeouts": "network_timeouts",
    "overlay_access": "overlay_access",
    "similarity": None,
    "public_audit": None,
}

# - a row with no module must name where its message comes from, so nobody reads a paraphrase as a quote
OWNER_WORDS = ("ruff", "basedpyright", "vulture", "deptry", "names the")


def rows() -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    for line in (REVIEW / "EXAMPLES.md").read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] not in {"Check", "---"} and not set(cells[0]) <= {"-"}:
            table[cells[0]] = cells[1:]
    return table


def named_checks() -> set[str]:
    """The checks the review README lists, by the module stem or tool name it uses."""
    text = (REVIEW / "README.md").read_text(encoding="utf-8")
    return {match.lower() for match in re.findall(r"^- `([A-Za-z_]+)(?:\.py)?`", text, re.MULTILINE)}


class ExamplesPageTests(unittest.TestCase):
    def test_every_check_in_the_readme_has_a_row(self):
        missing = named_checks() - set(rows())
        self.assertEqual(missing, set(), "add a row to scripts/review/EXAMPLES.md")

    def test_every_row_names_a_check_this_test_knows(self):
        self.assertEqual(set(rows()) - set(CHECKS), set(), "name the module or tool the row quotes")

    def test_a_quoted_template_still_exists_in_its_checker(self):
        for name, module in CHECKS.items():
            if module is None:
                continue
            cell = rows()[name][1]
            chunks = [chunk.strip(" `") for chunk in cell.split("...")]
            chunks = [chunk for chunk in chunks if len(chunk.strip()) >= 2]
            source = (CHECKS_DIR / f"{module}.py").read_text(encoding="utf-8")
            for chunk in chunks:
                self.assertIn(chunk, source, f"{name}: rewrite the row or the message it quotes")

    def test_a_row_without_a_quote_says_where_its_message_comes_from(self):
        for name, module in CHECKS.items():
            if module is not None:
                continue
            cell = rows()[name][1].lower()
            self.assertTrue(any(word in cell for word in OWNER_WORDS), f"{name}: name the tool or say 'names the'")


if __name__ == "__main__":
    unittest.main()
