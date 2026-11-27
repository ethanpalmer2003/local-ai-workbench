"""Check component ownership, install roots, root folders, folder naming and batch references."""

import ast
import re
import subprocess
import tomllib
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.config import paths as config_paths
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as update_config
from scripts.launchers import launcher_config as cfg
from scripts.review import MAX_REPORTED
from scripts.shared.file_sets import maintained_files, tracked_files

# - the host refuses a file past 100 MiB, so this sits below it and leaves room to act
LARGE_FILE_MIB = 50
BYTES_PER_MIB = 1024 * 1024


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
        for path in root.iterdir():
            if path.is_dir() and not path.name.startswith(".") and path.name not in allowed:
                issues.append(f"Unregistered install/model root: {path}")
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
    {"update_frameworks.bat", "_run.bat", "launch_llamacpp_pi_agent.bat", "launch_strata_pi_agent.bat"}
)
# - root folders that hold runtime data or tool state rather than tracked files; tool caches live under
#   scripts/state/cache instead, so a .pytest_cache or .ruff_cache here is a finding. graphify-out is the
#   junction the graph plugin's MCP server needs at its canonical path; the files are in the cache tree
RUNTIME_ROOTS = {
    "data",
    "frameworks",
    "trash",
    "graphify-out",
    ".git",
    ".venv",
    ".zed",
    "node_modules",
    "__pycache__",
    "runs",
}

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
        for role in ("launchers", "services", "maintenance", "models", "checks", "benchmarks", "browser", "manage")
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
    # - the review tree groups its checks by scope; the module is the owner, not a component
    if path.is_relative_to(project_cfg.SCRIPTS_DIR / "review"):
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
        if root == project_cfg.TEST_CASES_DIR and parts[0] in TEST_GROUPS:
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


PLACEMENT_NAMES: dict[Path, frozenset[str]] = {
    project_cfg.BASE_DIR: frozenset(
        {
            "README.md",
            "AGENTS.md",
            ".gitignore",
            ".gitattributes",
            ".codespell-ignore.txt",
            ".pre-commit-config.yaml",
            "pyproject.toml",
            "uv.lock",
        }
    ),
    project_cfg.SCRIPTS_DIR: frozenset({"__init__.py", "README.md", "AGENTS.md", ".env", ".gitignore"}),
    project_cfg.BAT_DIR: frozenset(ROOT_BATCHES | {"README.md", "_run.bat"}),
}

PLACEMENT_SUFFIXES: dict[Path, frozenset[str]] = {
    project_cfg.BASE_DIR / "notes": frozenset({".md"}),
    project_cfg.BASE_DIR / ".agents": frozenset({".md"}),
}

# - role trees apply to every folder inside them, not only their root
PLACEMENT_ROOTS: dict[Path, frozenset[str]] = {
    project_cfg.CONFIG_DIR: frozenset(
        {".py", ".md", ".json", ".patch", ".jinja", ".ini", ".txt", ".ts", ".yaml", ".kcpps"}
    ),
    project_cfg.SCRIPTS_DIR / "launchers": frozenset({".py", ".md", ".js", ".patch", ".diff", ".mjs"}),
    project_cfg.SCRIPTS_DIR / "tools": frozenset({".py", ".md", ".ps1"}),
    project_cfg.SCRIPTS_DIR / "review": frozenset({".py", ".md", ".bat"}),
    project_cfg.SCRIPTS_DIR / "download": frozenset({".py", ".md"}),
    project_cfg.BAT_DIR: frozenset({".bat", ".md"}),
}


def _folder_label(folder: Path) -> str:
    if folder == project_cfg.BASE_DIR:
        return "the workspace root"
    return folder.relative_to(project_cfg.BASE_DIR).as_posix()


def _placement_issues(path: Path) -> list[str] | None:
    """A folder accepts only the files its role allows, at any depth below that role."""
    label = _folder_label(path.parent)
    names = PLACEMENT_NAMES.get(path.parent)
    if names is not None and path.name not in names:
        return [f"File has no place in {label}: {path.name}"]
    suffixes = PLACEMENT_SUFFIXES.get(path.parent)
    if suffixes is not None and path.suffix not in suffixes:
        return [f"File has no place in {label}: {path.name}"]
    for root, allowed in PLACEMENT_ROOTS.items():
        if path.is_relative_to(root) and path.suffix not in allowed:
            return [f"File has no place in {label}: {path.name}"]
    return None


def owner_issues(path: Path) -> list[str]:
    root_batch = _root_batch_issues(path)
    if root_batch is not None:
        return root_batch
    if _exempt_area(path):
        return []
    return _owner_issue(path)


AREA_ROOTS = (project_cfg.TEST_CASES_DIR, project_cfg.SCRIPTS_DIR / "benchmarks")
# - test areas group by purpose rather than by component: personal media, repository review, suite entry points
TEST_GROUPS = {"personal", "review", "suites"}
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


def empty_shell_issues() -> list[str]:
    """A package that holds nothing but an empty __init__.py is a placeholder, not an owner."""
    issues: list[str] = []
    for folder in sorted({path.parent for path in tracked_files()}):
        if not folder.is_dir():
            continue
        entries = [entry for entry in folder.iterdir() if entry.is_file()]
        subfolders = [entry for entry in folder.iterdir() if entry.is_dir() and entry.name != "__pycache__"]
        if subfolders or not entries:
            continue
        if all(entry.name == "__init__.py" and entry.stat().st_size == 0 for entry in entries):
            issues.append(f"Empty package shell: {_folder_label(folder)}")
    return issues


# - every batch lives in the entry-point tree; these two wrappers sit beside the review guide that owns them
BATCH_WRAPPERS = ("scripts/review/check_repo.bat", "scripts/review/format_py.bat")


def batch_placement_issues() -> list[str]:
    """A batch outside the entry-point tree is only one of the wrappers its own guide links."""
    issues = []
    for path in tracked_files():
        if path.suffix != ".bat" or path.is_relative_to(project_cfg.BAT_DIR):
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        if relative not in BATCH_WRAPPERS:
            issues.append(f"Batch outside the entry-point tree: {relative}")
    return issues


# - every batch in the entry-point tree hands its run to the shared runner, which owns the venv path,
#   working directory, title, pause and exit code. These four start something the runner cannot:
#   the runner itself, the environment it installs into, and ComfyUI's own interpreter.
BATCH_RUNS_ALONE = frozenset(
    {
        "bat/_run.bat",
        "bat/models/sync_python_env.bat",
        "bat/browser/comfyui/comfyui_bootstrap.bat",
        "bat/browser/comfyui/launch_comfyui.bat",
    }
)
RUNNER_CALL = re.compile(r'call\s+"%~dp0[^"]*_run\.bat"', re.IGNORECASE)
VENV_PYTHON = re.compile(r"\.venv[\\/]Scripts[\\/]python\.exe", re.IGNORECASE)
COMMENT_LINE = re.compile(r"^\s*(?:rem\b|::)", re.IGNORECASE)


def _executed_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not COMMENT_LINE.match(line))


def batch_runner_issues() -> list[str]:
    """A batch sets RUN_MODULE and calls the runner; it never repeats what the runner owns."""
    issues = []
    for path in tracked_files():
        if path.suffix != ".bat" or not path.is_relative_to(project_cfg.BAT_DIR):
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        issues += _batch_runner_issue(relative, path.read_text(encoding="utf-8-sig"))
    return issues


def _batch_runner_issue(relative: str, text: str) -> list[str]:
    if relative in BATCH_RUNS_ALONE:
        return []
    executed = _executed_lines(text)
    if not RUNNER_CALL.search(executed):
        return [f"Batch hands no run to _run.bat: {relative}"]
    if VENV_PYTHON.search(executed):
        return [f"Batch runs the venv python itself instead of only _run.bat: {relative}"]
    return []


def state_issues() -> list[str]:
    """Runtime state keeps folders; a loose script or output dump belongs in a run folder or trash."""
    issues: list[str] = []
    for root in (project_cfg.STATE_DIR, project_cfg.STATE_DIR / "cache"):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_file():
                issues.append(f"Loose file in state: {_folder_label(entry)}")
    return issues


def root_folder_issues() -> list[str]:
    """A workspace-root folder that holds no tracked file and is not a runtime root is a leftover."""
    tracked_roots = {path.relative_to(project_cfg.BASE_DIR).parts[0] for path in tracked_files()}
    return [
        f"Unexpected root folder: {entry.name} (no tracked file, not a runtime root)"
        for entry in sorted(project_cfg.BASE_DIR.iterdir())
        if entry.is_dir() and entry.name not in RUNTIME_ROOTS and entry.name not in tracked_roots
    ]


def placement_issues() -> list[str]:
    """Every tracked file directly inside a high-level folder, whatever its type."""

    issues: list[str] = []
    for entry in tracked_files():
        if entry.parent in PLACEMENT_NAMES or entry.parent in PLACEMENT_SUFFIXES:
            issues += _placement_issues(entry) or []
    return issues


def large_file_issues(limit_mib: int | None = None) -> list[str]:
    """A tracked file past the host's per-file cap is refused at push, after the work is committed.

    The limit sits below that cap, so the file has room to become a release asset or go to trash instead of
    being discovered by a remote refusal.
    """
    limit = LARGE_FILE_MIB if limit_mib is None else limit_mib
    issues: list[str] = []
    for path in tracked_files():
        try:
            size_mib = path.stat().st_size / BYTES_PER_MIB
        except OSError:
            continue
        if size_mib > limit:
            issues.append(f"Tracked file over {limit} MiB: {_folder_label(path)} at {size_mib:.1f} MiB")
    return issues


TRASH_OWNER = "scripts/config/trash.py"


def trash_path_issues() -> list[str]:
    """The trash folder's path is built in one place, so its retention rule has one owner too.

    A second module that joins a `trash` segment can delete or prune what the owner decides to keep; both
    owners then need the same edit, and the one nobody remembers is the one that loses data.
    """
    issues: list[str] = []
    for path in maintained_files():
        if path.suffix != ".py":
            continue
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
        # - a fixture builds its own `trash` folder inside a temporary root, which is not this workspace's
        if relative == TRASH_OWNER or relative.startswith("scripts/tests/"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
                continue
            side = node.right
            if isinstance(side, ast.Constant) and side.value == "trash":
                issues.append(f"{relative}:{node.lineno}: joins a 'trash' path; import {TRASH_OWNER}")
    return issues


def indexed_files(root: Path | None = None) -> frozenset[str]:
    """Every path the commit would carry, staged additions included."""
    directory = root or project_cfg.BASE_DIR
    result = subprocess.run(
        ["git", "-C", str(directory), "ls-files", "-z"], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"git could not list the index: {result.stderr.strip()[:200]}")
    return frozenset(item for item in result.stdout.split("\0") if item)


def imported_modules(tree: ast.AST) -> set[str]:
    """Absolute `scripts.*` modules this file names in an import statement."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.startswith("scripts"))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module.startswith("scripts"):
            modules.add(node.module)
    return modules


def resolves_module(module: str, indexed: frozenset[str]) -> bool:
    """Whether the index carries this module as a file, a package, or a namespace package."""
    base = module.replace(".", "/")
    return (
        f"{base}.py" in indexed
        or f"{base}/__init__.py" in indexed
        or any(path.startswith(f"{base}/") for path in indexed)
    )


def ignored_indexed(root: Path | None = None) -> list[str]:
    """Indexed paths that also match an ignore rule: forced in, so a clone inherits generated state."""
    directory = root or project_cfg.BASE_DIR
    result = subprocess.run(
        ["git", "-C", str(directory), "ls-files", "-ci", "--exclude-standard", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"git could not list ignored index entries: {result.stderr.strip()[:200]}")
    return sorted(item for item in result.stdout.split("\0") if item)


def index_issues(root: Path | None = None) -> list[str]:
    """The index carries every `scripts.*` import it names, and no file an ignore rule covers.

    A file that exists here but not in the commit can satisfy an import while proving nothing about a
    clone; a file forced in under an ignored path is app-written state every later run has to fight.
    """
    directory = root or project_cfg.BASE_DIR
    indexed = indexed_files(directory)
    issues = [f"{path}: indexed but matches an ignore rule; never force it in" for path in ignored_indexed(directory)]
    for path in sorted(indexed):
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse((directory / path).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        issues.extend(
            f"{path}: imports {module}, which the index does not carry"
            for module in sorted(imported_modules(tree))
            if not resolves_module(module, indexed)
        )
    return issues


def main() -> int:
    files = maintained_files()
    issues = (
        configuration_issues()
        + physical_root_issues()
        + naming_issues()
        + policy_limit_issues()
        + placement_issues()
        + batch_placement_issues()
        + batch_runner_issues()
        + state_issues()
        + root_folder_issues()
        + large_file_issues()
        + trash_path_issues()
        + index_issues()
    )
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
