"""Check component ownership, config naming, imports and concise maintained documentation."""

import ast
import re
from functools import cache
from pathlib import Path
from urllib.parse import unquote

from scripts.config import models as model_cfg
from scripts.config import paths as config_paths
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import update_config
from scripts.launchers import launcher_config as cfg

GUIDE_WORDS = 500
RULE_WORDS = 300
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


def configuration_issues() -> list[str]:
    issues = []
    for key, paths in project_cfg.COMPONENTS.items():
        if key != paths.key or not re.fullmatch(r"[a-z0-9_-]+(?:/[a-z0-9_-]+)*", key):
            issues.append(f"Invalid component key: {key}")
    for module in (project_cfg, cfg):
        for name, value in vars(module).items():
            if name.isupper() and name.endswith("_DIR") and not isinstance(value, Path):
                issues.append(f"{module.__name__}.{name} must be a Path")
            if name in LEGACY_BINDINGS:
                issues.append(f"Legacy config binding: {module.__name__}.{name}")
    for model in model_cfg.MODELS:
        if model.group not in project_cfg.COMPONENTS:
            issues.append(f"Unknown model owner: {model.group}")
            continue
        if not model.label.startswith(model.group + "/"):
            issues.append(f"Model label does not match its owner: {model.label}")
        if not model.path.is_relative_to(project_cfg.component(model.group).models_dir):
            issues.append(f"Model destination does not match its owner: {model.label}")
    for tool in update_config.TOOLS:
        if not any(tool.name == key or tool.name.startswith(key + "/") for key in project_cfg.COMPONENTS):
            issues.append(f"Unknown updater owner: {tool.name}")
    for key in ("regression", "probes", "harnesses", "models"):
        old = project_cfg.TEST_CASES_DIR / key
        if old.is_dir() and any(
            p.suffix in (".py", ".cjs", ".md") for p in old.rglob("*") if "__pycache__" not in p.parts
        ):
            issues.append(f"Retired test category still owns source: {old.relative_to(project_cfg.BASE_DIR)}")
    return issues


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


def batch_issues(path: Path, text: str) -> list[str]:
    issues = []
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
    return issues


def owner_issues(path: Path) -> list[str]:
    # - updater, shutdown and coding-agent entry points may live at the bat root
    if path.parent == project_cfg.BAT_DIR and path.suffix == ".bat":
        root_batches = {
            "update_frameworks.bat",
            "build_frameworks.bat",
            "cleanup_state.bat",
            "manage_kill_ai_services.bat",
            "resume_command_code_session.bat",
            "launch_llamacpp_pi_agent.bat",
            "launch_strata_pi_agent.bat",
        }
        return [] if path.name in root_batches else [f"Unexpected root batch: {path.name}"]
    # The cross-component registry is a config API, not a runtime component.
    if path.is_relative_to(project_cfg.CONFIG_DIR / "models"):
        return []
    # Root configuration notes describe shared policy across components.
    if path.is_relative_to(project_cfg.CONFIG_DIR / "notes"):
        return []
    launcher_root = project_cfg.SCRIPTS_DIR / "launchers"
    if path.is_relative_to(launcher_root):
        top = path.relative_to(launcher_root).parts[0]
        if top == "runtime":
            return []
    roots = [
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
    ]
    for root in roots:
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
        if any(
            owner == key or owner.startswith(key + "/") or key.startswith(owner + "/") for key in project_cfg.COMPONENTS
        ):
            return []
        return [f"Unregistered component folder: {path.relative_to(project_cfg.BASE_DIR)}"]
    return []


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


def markdown_issues(path: Path, text: str) -> list[str]:
    issues = []
    relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    budget = 450 if relative == "AGENTS.md" else RULE_WORDS if relative.startswith(".agents/") else GUIDE_WORDS
    words = len(text.split())
    if words > budget:
        issues.append(f"{relative}: {words} words exceeds {budget}; keep procedures in one owner guide")
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


def naming_issues() -> list[str]:
    """Folder names across the workspace: lowercase snake_case, meaningful, and never duplicated by placement."""
    issues: list[str] = []
    area_roots = (project_cfg.TEST_CASES_DIR, project_cfg.SCRIPTS_DIR / "benchmarks")
    vague_areas = {"llm", "speech", "tts", "misc", "stuff", "temp", "utils", "data", "models", "tests"}
    vague_anywhere = {"misc", "stuff", "temp", "tmp", "utils", "other", "new", "old"}
    skip = EXCLUDED | {"shared"}
    roots = [
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
    ]
    for root in roots:
        if not root.is_dir():
            continue
        skills = root.name == "skills" and root.parent.name == ".agents"
        for folder in sorted(path for path in root.iterdir() if path.is_dir() and path.name not in skip):
            if folder.name.startswith("."):
                continue
            where = folder.relative_to(project_cfg.BASE_DIR).as_posix()
            groups = (
                [path for path in folder.iterdir() if path.is_dir() and path.name not in skip]
                if folder.name == "personal"
                else [folder]
            )
            for group in groups:
                if group.name in vague_anywhere or (root in area_roots and group.name in vague_areas):
                    issues.append(f"Folder name states neither workload nor engine: {where}")
                # - Agent Skills requires lowercase letters, digits and hyphens
                pattern = r"[a-z0-9][a-z0-9-]*" if skills else r"[a-z][a-z0-9_]*"
                if not re.fullmatch(pattern, group.name):
                    issues.append(f"Folder name breaks the {pattern} convention: {where}")
    for root in (project_cfg.TEST_CASES_DIR, project_cfg.SCRIPTS_DIR / "benchmarks"):
        personal = root / "personal"
        if not personal.is_dir():
            continue
        nested = {path.name for path in personal.iterdir() if path.is_dir()}
        siblings = {path.name for path in root.iterdir() if path.is_dir() and path.name not in skip | {"personal"}}
        for duplicate in sorted(nested & siblings):
            issues.append(f"Area sits both at the root and under personal/: {duplicate}")
    return issues


def main() -> int:
    issues = configuration_issues() + physical_root_issues() + naming_issues()
    files = maintained_files()
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        issues += owner_issues(path)
        if path.suffix == ".py":
            issues += source_issues(path, text)
        elif path.suffix == ".md":
            issues += markdown_issues(path, text)
        elif path.suffix == ".bat":
            issues += batch_issues(path, text)
    for issue in issues[:40]:
        print(f"[FAIL] {issue}")
    if len(issues) > 40:
        print(f"[WARN] {len(issues) - 40} further issues; output bounded at 40")
    print(f"[{'FAIL' if issues else 'OK'}] Structure/docs: {len(files)} files, {len(issues)} issues")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
