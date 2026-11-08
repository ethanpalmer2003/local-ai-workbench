"""Check component ownership, config naming, imports and concise maintained documentation."""

import argparse
import ast
import re
from functools import cache
from pathlib import Path
from urllib.parse import unquote

from scripts.config import models as model_cfg
from scripts.config import paths as config_paths
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as update_config
from scripts.launchers import launcher_config as cfg

GUIDE_WORDS = 500
README_WORDS = 750
AGENTS_WORDS = 450
RULE_WORDS = 300
# - names tooling requires keep their spelling; every other Markdown basename is uppercase
MARKDOWN_NAME_ALLOWED = frozenset({"README.md", "AGENTS.md", "SKILL.md"})
# - a document below this is a candidate for merging into its owner; reviewed, not failed
SHORT_DOCUMENT_WORDS = 100
# - review records state a dated decision, and the complexity ledger is generated
SHORT_DOCUMENT_SKIP = ("notes/reviews/", "scripts/review/COMPLEXITY-DEBT.md")
LEGACY_BINDINGS = {
    "KOBOLD",
    "STRATA",
    "ASR",
    "WHISPER_ASR",
    "PARAKEET_ASR",
    "QWEN_ASR",
    "KOKORO",
    "PI",
    "DSH",
    "OHMYPI",
    "LITTLECODER",
    "NANOCODER",
    "ACTIVE_LLAMACPP_BUILD",
    "ACTIVE_LLAMACPP_CODING_AGENT_PROFILE",
    "AUDIOCPP_DIR",
    "AUDIOCPP_ROCM_RELEASE_DIR",
    "HF_HUB_DIR",
    "COMFYUI_DIR",
    "SDCPP_OUT_DIR",
    "SDCPP_ROCM_BIN_DIR",
    "BENCHMARKS_DIR",
    "VIDEOGEN_MODELS_DIR",
}
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", "state", "output", "old", "retired", "comfyui-archive"}


def maintained_files() -> list[Path]:
    files = [project_cfg.BASE_DIR / "AGENTS.md", project_cfg.BASE_DIR / "README.md"]
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
    issues = []
    for module in (project_cfg, cfg):
        for name, value in vars(module).items():
            if name.isupper() and name.endswith("_DIR") and not isinstance(value, Path):
                issues.append(f"{module.__name__}.{name} must be a Path")
            if name in LEGACY_BINDINGS:
                issues.append(f"Legacy config binding: {module.__name__}.{name}")
    return issues


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


def source_issues(path: Path, text: str) -> list[str]:
    issues = []
    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("scripts."):
            target = project_cfg.BASE_DIR / node.module.replace(".", "/")
            if not target.is_dir() and not target.with_suffix(".py").is_file():
                issues.append(f"{path.name}:{node.lineno}: missing import {node.module}")
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
        "resume_command_code_session.bat",
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


def markdown_budget(relative: str, path: Path) -> int:
    """One cap per document role; a hub README carries tables, not policy."""
    if relative == "AGENTS.md":
        return AGENTS_WORDS
    if relative.startswith(".agents/"):
        return RULE_WORDS
    return README_WORDS if path.name.lower() == "readme.md" else GUIDE_WORDS


def short_candidate(relative: str, path: Path) -> bool:
    """Documents the review list owns; generated and tool-required files stay out of it."""
    return path.name not in MARKDOWN_NAME_ALLOWED and not relative.startswith(SHORT_DOCUMENT_SKIP)


def word_marker(words: int, budget: int, relative: str, path: Path) -> str:
    """Both ends at once: over the document budget, under the review floor, or neither."""
    if words > budget:
        return "over"
    return "short" if words < SHORT_DOCUMENT_WORDS and short_candidate(relative, path) else ""


def word_rows(files: list[Path]) -> list[tuple[int, int, str, str]]:
    """Every maintained document with its word count and budget, longest first."""
    rows = []
    for path in files:
        if path.suffix != ".md":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        budget = markdown_budget(relative, path)
        words = prose_words(path.read_text(encoding="utf-8-sig"))
        rows.append((words, budget, relative, word_marker(words, budget, relative, path)))
    return sorted(rows, reverse=True)


def print_word_counts(files: list[Path]) -> int:
    """One table covering both ends: the over-budget documents and the review candidates."""
    rows = word_rows(files)
    over = sum(1 for *_, marker in rows if marker == "over")
    short = sum(1 for *_, marker in rows if marker == "short")
    print(f"{'words':>6} {'budget':>6}  {'mark':6}  document")
    for words, budget, relative, marker in rows:
        print(f"{words:6d} {budget:6d}  {marker:6}  {relative}")
    print(f"{len(rows)} documents, {over} over budget, {short} under {SHORT_DOCUMENT_WORDS} words")
    return int(bool(over))


def markdown_issues(path: Path, text: str) -> list[str]:
    issues = []
    relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    budget = markdown_budget(relative, path)
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


def short_documents(files: list[Path]) -> list[tuple[int, str]]:
    """Documents too short to own a rule; listed for review, never failed."""
    short = []
    for path in files:
        if path.suffix != ".md":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        if not short_candidate(relative, path):
            continue
        words = prose_words(path.read_text(encoding="utf-8-sig"))
        if words < SHORT_DOCUMENT_WORDS:
            short.append((words, relative))
    return sorted(short)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", action="store_true", help="list every maintained document by word count")
    args = parser.parse_args(argv)
    if args.words:
        return print_word_counts(maintained_files())
    issues = configuration_issues() + physical_root_issues() + naming_issues()
    files = maintained_files()
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        issues += owner_issues(path)
        if path.suffix == ".py":
            issues += source_issues(path, text)
        elif path.suffix == ".md":
            issues += markdown_name_issues(path)
            issues += markdown_issues(path, text)
        elif path.suffix == ".bat":
            issues += batch_issues(path, text)
    for issue in issues[:40]:
        print(f"[FAIL] {issue}")
    if len(issues) > 40:
        print(f"[WARN] {len(issues) - 40} further issues; output bounded at 40")
    for words, relative in short_documents(files):
        print(f"[WARN] short document ({words} words): {relative}; merge it into its owner or justify it")
    print(f"[{'FAIL' if issues else 'OK'}] Structure/docs: {len(files)} files, {len(issues)} issues")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
