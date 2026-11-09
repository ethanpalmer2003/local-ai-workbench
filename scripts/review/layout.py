"""Check component ownership, install roots, folder naming and batch references."""

import re
import tomllib
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.config import paths as config_paths
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as update_config
from scripts.launchers import launcher_config as cfg
from scripts.review import MAX_REPORTED
from scripts.review.sources import maintained_files


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


AREA_ROOTS = (project_cfg.TEST_CASES_DIR, project_cfg.SCRIPTS_DIR / "benchmarks")
VAGUE_AREAS = {"llm", "speech", "tts", "misc", "stuff", "temp", "utils", "data", "models", "tests"}
VAGUE_ANYWHERE = {"misc", "stuff", "temp", "tmp", "utils", "other", "new", "old"}
NAME_SKIP = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "state",
    "output",
    "old",
    "retired",
    "comfyui-archive",
    "shared",
}
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


def policy_limit_issues() -> list[str]:
    """The documented complexity limit must match the configured one."""
    payload = tomllib.loads((project_cfg.BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    limit = payload.get("tool", {}).get("ruff", {}).get("lint", {}).get("mccabe", {}).get("max-complexity")
    rules = (project_cfg.BASE_DIR / ".agents" / "CODE.md").read_text(encoding="utf-8-sig")
    stated = re.search(r"[Mm]cCabe[^.\n]{0,20}?(\d+)", rules)
    if limit is None:
        return ["pyproject.toml has no McCabe limit"]
    if stated is None:
        return ["CODE.md does not state the McCabe limit"]
    if int(stated.group(1)) != int(limit):
        return [f"CODE.md states McCabe {stated.group(1)} but pyproject configures {limit}"]
    return []


def main() -> int:
    files = maintained_files()
    issues = configuration_issues() + physical_root_issues() + naming_issues() + policy_limit_issues()
    for path in files:
        issues += owner_issues(path)
        if path.suffix == ".bat":
            issues += batch_issues(path, path.read_text(encoding="utf-8-sig"))
    for issue in issues[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    if len(issues) > MAX_REPORTED:
        print(f"[WARN] {len(issues) - MAX_REPORTED} further issues; output bounded at {MAX_REPORTED}")
    print(f"[{'FAIL' if issues else 'OK'}] Layout: {len(files)} files, {len(issues)} issues")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
