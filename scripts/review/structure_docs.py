"""Check component ownership, config naming, imports and concise maintained documentation."""

import argparse
import re
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from scripts.config import models as model_cfg
from scripts.config import paths as config_paths
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as update_config
from scripts.launchers import launcher_config as cfg
from scripts.review import MAX_REPORTED

# - three caps only; each document role picks one, so a new kind needs no new number
WORD_TIERS = {"large": 700, "medium": 500, "small": 300}
ROLE_TIERS = {
    "root": "large",
    "hub": "large",
    "agent rule": "small",
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
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", "state", "output", "old", "retired", "comfyui-archive"}


def maintained_files() -> list[Path]:
    # - root documents are checked here and their placement is checked by root_document_issues()
    files = sorted(project_cfg.BASE_DIR.glob("*.md"))
    for root in (
        project_cfg.SCRIPTS_DIR,
        project_cfg.BAT_DIR,
        project_cfg.BASE_DIR / "notes",
        project_cfg.BASE_DIR / ".agents",
    ):
        pending = [root]
        while pending:
            for path in pending.pop().iterdir():
                if path.is_junction() or path.is_symlink():
                    continue
                if path.is_dir() and path.name not in EXCLUDED:
                    pending.append(path)
                elif path.is_file() and path.suffix in (".py", ".md", ".bat"):
                    files.append(path)
    return files


def _component_key_issues() -> list[str]:
    return [
        f"Invalid component key: {key}"
        for key, paths in project_cfg.COMPONENTS.items()
        if key != paths.key or not re.fullmatch(r"[a-z0-9_-]+(?:/[a-z0-9_-]+)*", key)
    ]


def _binding_issues() -> list[str]:
    return [
        f"{module.__name__}.{name} must be a Path"
        for module in (project_cfg, cfg)
        for name, value in vars(module).items()
        if name.isupper() and name.endswith("_DIR") and not isinstance(value, Path)
    ]


def _model_owner_issues() -> list[str]:
    issues = []
    for model in model_cfg.MODELS:
        if model.group not in project_cfg.COMPONENTS:
            issues.append(f"Unknown model owner: {model.group}")
            continue
        if not model.label.startswith(model.group + "/"):
            issues.append(f"Model label does not match its owner: {model.label}")
        if not model.path.is_relative_to(project_cfg.component(model.group).models_dir):
            issues.append(f"Model destination does not match its owner: {model.label}")
    return issues


def _updater_owner_issues() -> list[str]:
    return [
        f"Unknown updater owner: {tool.name}"
        for tool in update_config.TOOLS
        if not any(tool.name == key or tool.name.startswith(key + "/") for key in project_cfg.COMPONENTS)
    ]


def _retired_category_issues() -> list[str]:
    issues = []
    for key in ("regression", "probes", "harnesses", "models"):
        old = project_cfg.TEST_CASES_DIR / key
        if old.is_dir() and any(
            p.suffix in (".py", ".cjs", ".md") for p in old.rglob("*") if "__pycache__" not in p.parts
        ):
            issues.append(f"Retired test category still owns source: {old.relative_to(project_cfg.BASE_DIR)}")
    return issues


def configuration_issues() -> list[str]:
    return [
        *_component_key_issues(),
        *_binding_issues(),
        *_model_owner_issues(),
        *_updater_owner_issues(),
        *_retired_category_issues(),
    ]


def physical_root_issues() -> list[str]:
    issues = []
    for root, paths in (
        (project_cfg.FRAMEWORKS_DIR, [item.framework_dir for item in project_cfg.COMPONENTS.values()]),
        (project_cfg.HF_MODELS_DIR, [item.models_dir for item in project_cfg.COMPONENTS.values()]),
    ):
        if not root.is_dir():
            continue
        allowed = {p.relative_to(root).parts[0] for p in paths if p.is_relative_to(root)}
        if root == project_cfg.HF_MODELS_DIR:
            allowed.update(project_cfg.MODEL_ALIASES)
        for path in root.iterdir():
            if path.is_dir() and not path.name.startswith(".") and path.name not in allowed:
                issues.append(f"Unregistered install/model root: {path}")
    for alias, owner in project_cfg.MODEL_ALIASES.items():
        path = project_cfg.HF_MODELS_DIR / alias
        if path.exists() and path.resolve() != project_cfg.component(owner).models_dir.resolve():
            issues.append(f"Model alias {alias} does not resolve to {owner}")
    native = project_cfg.component("comfyui").config_dir / "extra_model_paths.yaml"
    match = re.search(r'^\s*base_path:\s*"([^"]+)"', config_paths.load_text(native), re.M)
    if not match or Path(match.group(1)) != project_cfg.component("comfyui").models_dir:
        issues.append("ComfyUI native model mapping differs from COMPONENTS")
    return issues


BARE_BATCH = re.compile(r"^[\w.\\/ -]+\.bat$", re.IGNORECASE)
BATCH_COMMANDS = re.compile(r"^(?:call|start|cmd|explorer|if|for|echo|title|rem)\b", re.IGNORECASE)


def _bare_batch_issue(path: Path, text: str) -> list[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if BARE_BATCH.fullmatch(stripped) and not BATCH_COMMANDS.match(stripped):
            return [f"{path.name}: invoke `{stripped}` through `call` or `start`, or the parent never resumes"]
    return []


def batch_issues(path: Path, text: str) -> list[str]:
    issues = []
    if text.startswith("\ufeff"):
        issues.append(f"{path.name}: UTF-8 BOM; cmd.exe cannot parse a BOM-prefixed batch file")
    for match in re.finditer(r"-m (scripts\.[A-Za-z_0-9.]+)", text):
        target = project_cfg.BASE_DIR / match.group(1).replace(".", "/")
        if not target.is_dir() and not target.with_suffix(".py").is_file():
            issues.append(f"{path.name}: missing module {match.group(1)}")
    for match in re.finditer(r'%~dp0([^"%\r\n]+?\.bat)', text, re.I):
        if not (path.parent / match.group(1)).is_file():
            issues.append(f"{path.name}: missing relative batch {match.group(1)}")
    if "from scripts.config import project_config as p" in text:
        for match in re.finditer(r"\bp\.([A-Z][A-Z_0-9]+)", text):
            if not hasattr(project_cfg, match.group(1)):
                issues.append(f"{path.name}: missing project binding {match.group(1)}")
    return [*issues, *_bare_batch_issue(path, text)]


ROOT_BATCHES = frozenset(
    {
        "update_frameworks.bat",
        "build_frameworks.bat",
        "cleanup_state.bat",
        "manage_kill_ai_services.bat",
        "launch_llamacpp_pi_agent.bat",
        "launch_strata_pi_agent.bat",
    }
)

OWNER_ROOTS = (
    project_cfg.CONFIG_DIR,
    project_cfg.SCRIPTS_DIR / "benchmarks",
    project_cfg.SCRIPTS_DIR / "launchers",
    project_cfg.SCRIPTS_DIR / "tools",
    project_cfg.SCRIPTS_DIR / "review",
    project_cfg.TEST_CASES_DIR,
    project_cfg.TESTS_DIR / "ui",
    project_cfg.SCRIPTS_DIR / "download/frameworks",
    *(
        project_cfg.BAT_DIR / role
        for role in ("launchers", "services", "maintenance", "models", "tests", "benchmarks", "browser")
    ),
)


def _root_batch_issues(path: Path) -> list[str] | None:
    """Updater, shutdown and coding-agent entry points may live at the bat root."""
    if not (path.parent == project_cfg.BAT_DIR and path.suffix == ".bat"):
        return None
    return [] if path.name in ROOT_BATCHES else [f"Unexpected root batch: {path.name}"]


def _exempt_area(path: Path) -> bool:
    # - the cross-component registry is a config API, and root config notes are shared policy
    if path.is_relative_to(project_cfg.CONFIG_DIR / "models"):
        return True
    if path.is_relative_to(project_cfg.CONFIG_DIR / "notes"):
        return True
    launcher_root = project_cfg.SCRIPTS_DIR / "launchers"
    return path.is_relative_to(launcher_root) and path.relative_to(launcher_root).parts[0] == "runtime"


def _owner_issue(path: Path) -> list[str]:
    for root in OWNER_ROOTS:
        if not path.is_relative_to(root):
            continue
        if root == project_cfg.SCRIPTS_DIR / "benchmarks":
            return []
        parts = path.relative_to(root).parts
        if root == project_cfg.TEST_CASES_DIR and parts[0] == "personal":
            # - personal media/chat areas keep their own group folder
            return []
        if len(parts) == 1:
            # - routine batches may sit directly under an operation folder (flattened layout)
            return []
        owner = "/".join(parts[:-1])
        registered = any(
            owner == key or owner.startswith(key + "/") or key.startswith(owner + "/") for key in project_cfg.COMPONENTS
        )
        if registered:
            return []
        return [f"Unregistered component folder: {path.relative_to(project_cfg.BASE_DIR)}"]
    return []


def owner_issues(path: Path) -> list[str]:
    root_batch = _root_batch_issues(path)
    if root_batch is not None:
        return root_batch
    if _exempt_area(path):
        return []
    return _owner_issue(path)


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


def prose_words(text: str) -> int:
    """Words a reader reads: code fences, inline code, link targets and table rules are structure."""
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]*`", " ", cleaned)
    cleaned = re.sub(r"\]\([^)]*\)", "] ", cleaned)
    cleaned = re.sub(r"(?m)^\s*\|[-: |]+\|\s*$", " ", cleaned)
    return len(cleaned.replace("|", " ").split())


def markdown_budget(relative: str) -> int:
    """One of three caps, chosen by the role the document's home gives it."""
    return WORD_TIERS[ROLE_TIERS.get(document_role(relative) or "", "medium")]


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


MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def pointer_stats(files: list[Path]) -> dict[str, Any]:
    """Where Markdown points: internal pointers per target and source, plus external and non-Markdown links."""
    sources: Counter[str] = Counter()
    targets: Counter[str] = Counter()
    external = other = 0
    for path in files:
        if path.suffix != ".md":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        for match in MARKDOWN_LINK.finditer(path.read_text(encoding="utf-8-sig")):
            target = unquote(match.group(1).strip("<>").split(" ")[0]).partition("#")[0]
            if not target:
                continue
            if re.match(r"^[a-z]+:", target, re.I):
                external += 1
                continue
            if not target.endswith(".md"):
                other += 1
                continue
            destination = (path.parent / target).resolve()
            key = (
                destination.relative_to(project_cfg.BASE_DIR).as_posix()
                if destination.is_relative_to(project_cfg.BASE_DIR)
                else str(destination)
            )
            sources[relative] += 1
            targets[key] += 1
    maintained = {path.relative_to(project_cfg.BASE_DIR).as_posix() for path in files if path.suffix == ".md"}
    return {
        "sources": sources,
        "targets": targets,
        "external": external,
        "other": other,
        "unlinked": sorted(maintained - set(targets)),
    }


def print_pointer_counts(files: list[Path]) -> int:
    """Markdown pointers, the most-linked documents and the ones nothing points at."""
    stats = pointer_stats(files)
    targets: Counter[str] = stats["targets"]
    sources: Counter[str] = stats["sources"]
    print(f"{sum(targets.values())} Markdown pointers from {len(sources)} documents to {len(targets)} targets")
    print(f"{stats['external']} external links; {stats['other']} links to other files")
    print("\nmost linked:")
    for name, count in targets.most_common(10):
        print(f"{count:5}  {name}")
    unlinked: list[str] = stats["unlinked"]
    print(f"\n{len(unlinked)} document(s) no other document points at:")
    for name in unlinked:
        print(f"       {name}")
    return 0


def markdown_issues(path: Path, text: str) -> list[str]:
    issues = []
    relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    budget = markdown_budget(relative)
    words = prose_words(text)
    if words > budget:
        issues.append(f"{relative}: {words} words exceeds {budget}; keep procedures in one owner guide")
    issues.extend(_markdown_hygiene(relative, text))
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
        target, _, anchor = unquote(match.group(1).strip("<>")).partition("#")
        if re.match(r"^[a-z]+:", target, re.I):
            continue
        if any(part in target.split("/") for part in ("output", "old", "retired", "trash")):
            continue
        destination = path.parent / target if target else path
        if not destination.exists():
            issues.append(f"{relative}: missing link {target}")
        elif anchor and destination.suffix == ".md" and anchor not in markdown_anchors(destination):
            issues.append(f"{relative}: missing heading {target}#{anchor}")
    for match in re.finditer(r"(?i)(?:C:[/\\]AI[/\\])?(bat[/\\][^`\"\r\n]*?\.bat)", text):
        target = match.group(1).replace("\\", "/")
        if any(char in target for char in "<>*{}"):
            continue
        if not (project_cfg.BASE_DIR / target).is_file():
            issues.append(f"{relative}: missing batch entry {target}")
    return issues


AREA_ROOTS = (project_cfg.TEST_CASES_DIR, project_cfg.SCRIPTS_DIR / "benchmarks")
VAGUE_AREAS = {"llm", "speech", "tts", "misc", "stuff", "temp", "utils", "data", "models", "tests"}
VAGUE_ANYWHERE = {"misc", "stuff", "temp", "tmp", "utils", "other", "new", "old"}
NAME_SKIP = EXCLUDED | {"shared"}
NAMING_ROOTS = (
    project_cfg.TEST_CASES_DIR,
    project_cfg.SCRIPTS_DIR / "benchmarks",
    project_cfg.SCRIPTS_DIR / "config",
    project_cfg.SCRIPTS_DIR / "launchers",
    project_cfg.SCRIPTS_DIR / "download",
    project_cfg.SCRIPTS_DIR / "review",
    project_cfg.SCRIPTS_DIR / "tools",
    project_cfg.BAT_DIR,
    project_cfg.BASE_DIR / "notes",
    project_cfg.BASE_DIR / ".agents",
)


def _folder_name_issues(folder: Path, root: Path, where: str, skills: bool) -> list[str]:
    issues = []
    if folder.name in VAGUE_ANYWHERE or (root in AREA_ROOTS and folder.name in VAGUE_AREAS):
        issues.append(f"Folder name states neither workload nor engine: {where}")
    # - Agent Skills requires lowercase letters, digits and hyphens
    pattern = r"[a-z0-9][a-z0-9-]*" if skills else r"[a-z][a-z0-9_]*"
    if not re.fullmatch(pattern, folder.name):
        issues.append(f"Folder name breaks the {pattern} convention: {where}")
    return issues


def _root_naming_issues(root: Path) -> list[str]:
    skills = root.name == "skills" and root.parent.name == ".agents"
    issues = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir() and path.name not in NAME_SKIP):
        if folder.name.startswith("."):
            continue
        where = folder.relative_to(project_cfg.BASE_DIR).as_posix()
        groups = (
            [path for path in folder.iterdir() if path.is_dir() and path.name not in NAME_SKIP]
            if folder.name == "personal"
            else [folder]
        )
        for group in groups:
            issues.extend(_folder_name_issues(group, root, where, skills))
    return issues


def _duplicate_area_issues() -> list[str]:
    issues = []
    for root in AREA_ROOTS:
        personal = root / "personal"
        if not personal.is_dir():
            continue
        nested = {path.name for path in personal.iterdir() if path.is_dir()}
        siblings = {path.name for path in root.iterdir() if path.is_dir() and path.name not in NAME_SKIP | {"personal"}}
        issues.extend(f"Area sits both at the root and under personal/: {name}" for name in sorted(nested & siblings))
    return issues


def naming_issues() -> list[str]:
    """Folder names across the workspace: lowercase snake_case, meaningful, and never duplicated by placement."""
    issues: list[str] = []
    for root in NAMING_ROOTS:
        if root.is_dir():
            issues.extend(_root_naming_issues(root))
    issues.extend(_duplicate_area_issues())
    return issues


def markdown_name_issues(path: Path) -> list[str]:
    """Markdown basenames are uppercase, so a document is recognizable across the workspace."""
    if path.name in MARKDOWN_NAME_ALLOWED or path.stem == path.stem.upper():
        return []
    return [f"{path.relative_to(project_cfg.BASE_DIR).as_posix()}: Markdown basename must be uppercase"]


# - one home per role: the table is the whole taxonomy, so an unlisted kind fails instead of drifting in
RUNNING_LISTS = frozenset({"TODO.md", "OPEN-QUESTIONS.md", "UPSTREAM.md"})
ROLE_RULES = (
    ("root", r"(?:README|AGENTS)\.md"),
    ("agent rule", r".*AGENTS\.md|\.agents/.*\.md"),
    ("review record", r"notes/reviews/.*\.md"),
    ("note", r"notes/.*\.md"),
    ("hub", r"^(?:[^/]+/)+README\.md$"),
    ("component guide", r"scripts/(?:[^/]+/)+[A-Z][A-Z0-9-]*\.md"),
)


def document_role(relative: str) -> str | None:
    """The role a document's home and basename give it, or None when it matches no known kind."""
    for role, pattern in ROLE_RULES:
        if re.fullmatch(pattern, relative):
            return role
    return None


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


def root_document_issues() -> list[str]:
    """The root is navigation only; guides and running lists belong under notes/."""
    return [
        f"{path.name}: move root documents to notes/; only README.md and AGENTS.md stay here"
        for path in sorted(project_cfg.BASE_DIR.glob("*.md"))
        if path.name not in ROOT_MARKDOWN_ALLOWED
    ]


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
    issues = configuration_issues() + physical_root_issues() + naming_issues() + root_document_issues()
    issues += role_issues(files)
    issues += model_name_issues(files)
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        issues += owner_issues(path)
        if path.suffix == ".md":
            issues += markdown_name_issues(path)
            issues += markdown_issues(path, text)
        elif path.suffix == ".bat":
            issues += batch_issues(path, text)
    for issue in issues[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    if len(issues) > MAX_REPORTED:
        print(f"[WARN] {len(issues) - MAX_REPORTED} further issues; output bounded at {MAX_REPORTED}")
    print(f"[{'FAIL' if issues else 'OK'}] Structure/docs: {len(files)} files, {len(issues)} issues")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
