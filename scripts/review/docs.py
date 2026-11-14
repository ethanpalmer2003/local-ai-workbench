"""Check maintained Markdown: placement, roles, budgets, links and model-name policy."""

import argparse
import re
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.sources import maintained_files

# - three caps only; each document role picks one, so a new kind needs no new number
WORD_TIERS = {"long": 1000, "large": 700, "medium": 500}
ROLE_TIERS = {
    "hub": "large",
    "agent rule": "medium",
    "running list": "long",
    "generated page": "long",
    "note": "medium",
    "review record": "medium",
    "component guide": "medium",
}
# - names tooling requires keep their spelling; every other Markdown basename is uppercase
MARKDOWN_NAME_ALLOWED = frozenset({"README.md", "AGENTS.md", "SKILL.md"})
# - only these sit at the workspace root; every other document lives under notes/
ROOT_MARKDOWN_ALLOWED = frozenset({"README.md", "AGENTS.md"})
# - the catalog documents itself, dated evidence keeps its instances, and native layouts name vendor files
MODEL_NAME_ALLOWED = (
    "scripts/config/models/",
    "scripts/config/sdcpp/QUANTIZED.md",
    "notes/reviews/",
    "scripts/tests/notes/",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# - evidence and retired trees are not maintained documents, so a pointer into them will not survive a clone
UNTRACKED_PARTS = frozenset({"output", "old", "retired", "trash"})
# - one home per role: the table is the whole taxonomy, so an unlisted kind fails instead of drifting in
RUNNING_LISTS = frozenset(
    {"TODO.md", "OPEN-QUESTIONS.md", "OPEN-QUESTIONS-RESOLVED.md", "UPSTREAM-INDEX.md", "GROUPINGS-INDEX.md"}
)
# - indexes that grow with every decision get the long cap; they are read for one row, not one rule
RUNNING_LIST_PATHS = (
    r"notes/(?:TODO|OPEN-QUESTIONS|OPEN-QUESTIONS-RESOLVED|UPSTREAM-INDEX|GROUPINGS-INDEX|NATIVE-VALIDATION|ONBOARDING)\.md",
    r"scripts/tests/notes/(?:STATUS-INDEX|STATUS-EVIDENCE-INDEX|OUTCOMES|ESTIMATES)\.md",
)
ROLE_RULES = (
    ("hub", r"(?:.*/)?(?:README|AGENTS)\.md"),
    ("agent rule", r".*AGENTS\.md|\.agents/.*\.md"),
    ("review record", r"notes/reviews/.*\.md"),
    ("generated page", r"scripts/(?:config|tests)/notes/[A-Z][A-Z0-9-]*-MATRIX\.md"),
    ("running list", "|".join(RUNNING_LIST_PATHS)),
    ("note", r"notes/.*\.md"),
    ("component guide", r"scripts/(?:[^/]+/)+[A-Z][A-Z0-9-]*\.md"),
)
# - a policy number is stated once; every other document links to its owner instead of repeating it
POLICY_NUMBERS = (
    (
        r"\b(?:500|700|1000)\s+words\b|\b(?:large|medium|long),\s*(?:500|700|1000)\b",
        "word caps",
        ".agents/NOTES-CONVENTIONS.md",
    ),
    (r"[Mm]cCabe[^.\n]{0,20}\b10\b", "McCabe limit", ".agents/CODE.md"),
)


def policy_number_issues(relative: str, text: str) -> list[str]:
    """A policy number lives in one owning document; anything else states it again."""
    issues = []
    for pattern, name, owner in POLICY_NUMBERS:
        if relative != owner and re.search(pattern, text):
            issues.append(f"{relative}: restates the {name}; that number is owned by {owner}")
    return issues


def cap_table_issues() -> list[str]:
    """The caps the docs state must match the tiers the gate uses."""
    rules = (project_cfg.BASE_DIR / ".agents" / "NOTES-CONVENTIONS.md").read_text(encoding="utf-8-sig")
    stated = {tier: int(number) for tier, number in re.findall(r"\|\s*(long|large|medium|small),\s*(\d+)\s*\|", rules)}
    issues = [
        f"NOTES-CONVENTIONS states {tier} {stated[tier]} words but the gate uses {WORD_TIERS[tier]}"
        for tier in WORD_TIERS
        if tier in stated and stated[tier] != WORD_TIERS[tier]
    ]
    issues.extend(f"NOTES-CONVENTIONS does not state the {tier} cap" for tier in WORD_TIERS if tier not in stated)
    return issues


def document_role(relative: str) -> str | None:
    """The role a document's home and basename give it, or None when it matches no known kind."""
    for role, pattern in ROLE_RULES:
        if re.fullmatch(pattern, relative):
            return role
    return None


def markdown_budget(relative: str) -> int:
    """One of three caps, chosen by the role the document's home gives it."""
    return WORD_TIERS[ROLE_TIERS.get(document_role(relative) or "", "medium")]


def markdown_name_issues(path: Path) -> list[str]:
    """Markdown basenames are uppercase, so a document is recognizable across the workspace."""
    if path.name in MARKDOWN_NAME_ALLOWED or path.stem == path.stem.upper():
        return []
    return [f"{path.relative_to(project_cfg.BASE_DIR).as_posix()}: Markdown basename must be uppercase"]


def root_document_issues() -> list[str]:
    """The root is navigation only; guides and running lists belong under notes/."""
    return [
        f"{path.name}: move root documents to notes/; only README.md and AGENTS.md stay here"
        for path in sorted(project_cfg.BASE_DIR.glob("*.md"))
        if path.name not in ROOT_MARKDOWN_ALLOWED
    ]


def _component_folder(path: Path) -> bool:
    return any(path.as_posix().endswith("/" + key) for key in project_cfg.COMPONENTS)


def _role_placement_issues(path: Path, relative: str) -> list[str]:
    if path.name in RUNNING_LISTS and path.parent != project_cfg.BASE_DIR / "notes":
        return [f"{relative}: running lists live at the notes root, not beside a component"]
    if path.name == "TUNING.md" and not _component_folder(path.parent):
        return [f"{relative}: TUNING.md belongs in a component folder"]
    return []


def role_issues(files: list[Path]) -> list[str]:
    """Every maintained document must claim a role, and its role must allow that home."""
    issues: list[str] = []
    for path in files:
        if path.suffix != ".md":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        issues.extend(_role_placement_issues(path, relative))
        if document_role(relative) is None:
            issues.append(f"{relative}: no document role; add the kind to ROLE_RULES or move the document")
    return issues


def print_role_counts(files: list[Path]) -> int:
    """How many maintained documents each role holds, unclassified last."""
    counts = Counter(
        document_role(path.relative_to(project_cfg.BASE_DIR).as_posix()) or "unclassified"
        for path in files
        if path.suffix == ".md"
    )
    for role, count in counts.most_common():
        print(f"{count:4d}  {role}")
    return int("unclassified" in counts)


def prose_words(text: str) -> int:
    """Words a reader reads: code fences, inline code, link targets and table rules are structure."""
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]*`", " ", cleaned)
    cleaned = re.sub(r"\]\([^)]*\)", "] ", cleaned)
    cleaned = re.sub(r"(?m)^\s*\|[-: |]+\|\s*$", " ", cleaned)
    return len(cleaned.replace("|", " ").split())


def word_rows(files: list[Path]) -> list[tuple[int, int, str, bool]]:
    """Every maintained document with its word count, budget and whether it exceeds it."""
    rows = []
    for path in files:
        if path.suffix != ".md":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        budget = markdown_budget(relative)
        words = prose_words(path.read_text(encoding="utf-8-sig"))
        rows.append((words, budget, relative, words > budget))
    return sorted(rows, reverse=True)


def print_word_counts(files: list[Path]) -> int:
    """The over-budget documents, longest first."""
    rows = word_rows(files)
    over = sum(1 for *_, exceeded in rows if exceeded)
    print(f"{'words':>6} {'budget':>6}  {'mark':6}  document")
    for words, budget, relative, exceeded in rows:
        print(f"{words:6d} {budget:6d}  {'over' if exceeded else '':6}  {relative}")
    print(f"{len(rows)} documents, {over} over budget")
    return int(bool(over))


def pointer_stats(files: list[Path]) -> dict[str, Any]:
    """Markdown pointers by source and target, with duplicates, self links, anchors and untracked targets."""
    sources: Counter[str] = Counter()
    targets: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    self_links = anchors = external = other = 0
    untracked: set[str] = set()
    for path in files:
        if path.suffix != ".md":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        for match in MARKDOWN_LINK.finditer(path.read_text(encoding="utf-8-sig")):
            raw = match.group(1).strip("<>").split(" ")[0]
            target, _, _anchor = unquote(raw).partition("#")
            if not target:
                anchors += 1
                continue
            if re.match(r"^[a-z]+:", target, re.I):
                external += 1
                continue
            if not target.endswith(".md"):
                other += 1
                continue
            destination = (path.parent / target).resolve()
            if destination == path.resolve():
                self_links += 1
                continue
            key = (
                destination.relative_to(project_cfg.BASE_DIR).as_posix()
                if destination.is_relative_to(project_cfg.BASE_DIR)
                else str(destination)
            )
            if UNTRACKED_PARTS & set(Path(target).parts):
                untracked.add(key)
            sources[relative] += 1
            targets[key] += 1
            pairs[(relative, key)] += 1
    maintained = {path.relative_to(project_cfg.BASE_DIR).as_posix() for path in files if path.suffix == ".md"}
    return {
        "sources": sources,
        "targets": targets,
        "duplicates": sorted((pair for pair, count in pairs.items() if count > 1), key=lambda pair: pair),
        "external": external,
        "other": other,
        "self_links": self_links,
        "anchors": anchors,
        "untracked": sorted(untracked),
        "unlinked": sorted(maintained - set(targets)),
    }


def print_pointer_counts(files: list[Path]) -> int:
    """Markdown pointers, the most-linked documents and the ones nothing points at."""
    stats = pointer_stats(files)
    targets: Counter[str] = stats["targets"]
    print(f"{sum(targets.values())} Markdown pointers from {len(stats['sources'])} documents to {len(targets)} targets")
    print(f"{stats['external']} external links; {stats['other']} links to other files")
    print(
        f"{stats['self_links']} self links; {stats['anchors']} same-document anchors; "
        f"{len(stats['duplicates'])} documents link one target more than once"
    )
    for source, target in stats["duplicates"]:
        print(f"  again  {source} -> {target}")
    untracked: list[str] = stats["untracked"]
    print(f"{len(untracked)} untracked target(s) linked (absent from a clone):")
    for name in untracked:
        print(f"       {name}")
    print("\nmost linked:")
    for name, count in targets.most_common(10):
        print(f"{count:5}  {name}")
    unlinked: list[str] = stats["unlinked"]
    print(f"\n{len(unlinked)} document(s) no other document points at:")
    for name in unlinked:
        print(f"       {name}")
    return 0


@cache
def markdown_anchors(path: Path) -> set[str]:
    anchors = set()
    fenced = False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            anchors.add(re.sub(r"[^\w\s-]", "", title).replace(" ", "-"))
    return anchors


def _markdown_hygiene(relative: str, text: str) -> list[str]:
    """Whitespace and fence drift a formatter would otherwise own."""
    issues = []
    if not text.endswith("\n"):
        issues.append(f"{relative}: no final newline")
    if "\t" in text:
        issues.append(f"{relative}: tab characters; markdown uses spaces")
    if text.count("```") % 2:
        issues.append(f"{relative}: unclosed code fence")
    previous = 0
    for line in text.splitlines():
        if line.rstrip() != line:
            issues.append(f"{relative}: trailing whitespace")
            break
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s", line)
        if not match:
            continue
        level = len(match.group(1))
        if previous and level > previous + 1:
            issues.append(f"{relative}: heading level jumps from {previous} to {level}")
            break
        previous = level
    return issues


def _link_problem(relative: str, raw: str, target: str) -> str | None:
    """Why a link target is unusable, or None when target checks can proceed."""
    if UNTRACKED_PARTS & set(target.split("/")):
        return f"{relative}: link into an untracked path {target}; cite the run without a link"
    if re.match(r"^[a-z]+:", target, re.I):
        return f"{relative}: unsupported link scheme {target}"
    if re.match(r"^[A-Za-z]:|^/", target):
        return f"{relative}: absolute link {target}; links must be relative"
    if "\\" in target:
        return f"{relative}: backslash in link {target}; use forward slashes"
    if " " in raw and not raw.startswith("<"):
        return f"{relative}: link with a space {target}; wrap the target in angle brackets"
    return None


def _link_issues(path: Path, relative: str, text: str) -> list[str]:
    issues = []
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
        raw = match.group(1).strip()
        target, _, anchor = unquote(raw.strip("<>")).partition("#")
        if re.match(r"^https?://|^mailto:", target, re.I):
            continue
        problem = _link_problem(relative, raw, target)
        if problem is not None:
            issues.append(problem)
            continue
        destination = path.parent / target if target else path
        if not destination.exists():
            issues.append(f"{relative}: missing link {target}")
        elif anchor and destination.suffix == ".md" and anchor not in markdown_anchors(destination):
            issues.append(f"{relative}: missing heading {target}#{anchor}")
    return issues


def _batch_reference_issues(relative: str, text: str) -> list[str]:
    issues = []
    for match in re.finditer(r"(?i)(?:C:[/\\]AI[/\\])?(bat[/\\][^`\"\r\n]*?\.bat)", text):
        target = match.group(1).replace("\\", "/")
        if any(char in target for char in "<>*{}"):
            continue
        if not (project_cfg.BASE_DIR / target).is_file():
            issues.append(f"{relative}: missing batch entry {target}")
    return issues


def _module_reference_issues(relative: str, text: str) -> list[str]:
    """A documented `python -m scripts.<module>` must name a module that exists."""
    issues = []
    for match in re.finditer(r"python -m (scripts(?:\.[A-Za-z_0-9]+)+)", text):
        module = match.group(1)
        target = project_cfg.BASE_DIR / module.replace(".", "/")
        if not target.with_suffix(".py").is_file() and not target.is_dir():
            issues.append(f"{relative}: names a missing module {module}")
    return issues


def markdown_issues(path: Path, text: str) -> list[str]:
    issues = []
    relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    budget = markdown_budget(relative)
    words = prose_words(text)
    if words > budget:
        issues.append(f"{relative}: {words} words exceeds {budget}; keep procedures in one owner guide")
    issues.extend(_markdown_hygiene(relative, text))
    issues.extend(_link_issues(path, relative, text))
    issues.extend(_batch_reference_issues(relative, text))
    issues.extend(_module_reference_issues(relative, text))
    issues.extend(policy_number_issues(relative, text))
    return issues


def model_names_skipped(relative: str) -> bool:
    """The catalog, dated evidence and native layouts may name an instance."""
    return relative.startswith(MODEL_NAME_ALLOWED)


def model_name_issues(files: list[Path]) -> list[str]:
    """Model ids and weight filenames live in the catalog; a document names the role instead."""
    terms = [model.label for model in model_cfg.MODELS]
    terms.extend(Path(model.filename).name for model in model_cfg.MODELS if model.filename)
    named = sorted((term for term in terms if len(term) >= 6), key=len, reverse=True)
    issues = []
    for path in files:
        if path.suffix != ".md":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        if model_names_skipped(relative):
            continue
        text = path.read_text(encoding="utf-8-sig")
        found = next((term for term in named if term in text), None)
        if found:
            issues.append(f"{relative}: names a catalog model ({found}); name the role and link the catalog")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", action="store_true", help="list every maintained document by word count")
    parser.add_argument("--roles", action="store_true", help="list every maintained document by role")
    parser.add_argument("--links", action="store_true", help="report Markdown pointers and unlinked documents")
    args = parser.parse_args(argv)
    files = maintained_files()
    if args.words:
        return print_word_counts(files)
    if args.roles:
        return print_role_counts(files)
    if args.links:
        return print_pointer_counts(files)
    issues = root_document_issues() + role_issues(files) + model_name_issues(files) + cap_table_issues()
    for path in files:
        if path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8-sig")
        issues += markdown_name_issues(path)
        issues += markdown_issues(path, text)
    for issue in issues[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    if len(issues) > MAX_REPORTED:
        print(f"[WARN] {len(issues) - MAX_REPORTED} further issues; output bounded at {MAX_REPORTED}")
    for source, target in list(pointer_stats(files)["duplicates"])[:MAX_REPORTED]:
        print(f"[WARN] repeated pointer: {source} -> {target}")
    print(f"[{'FAIL' if issues else 'OK'}] Docs: {len(files)} files, {len(issues)} issues")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
