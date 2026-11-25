"""Only static imports: a module loaded by name or path hides the dependency from every reader.

The suite's scope follows the import graph, and that graph is parsed from source, so a module name
built at runtime is invisible to it and the class that should have run is not selected. Eight places
earn an exception, each listed with the reason it cannot be written as an import statement.
"""

import ast
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import check_targets
from scripts.shared.paths import display_path

LOADERS = frozenset(
    {
        "__import__",
        "importlib.import_module",
        "importlib.util.spec_from_file_location",
        "runpy.run_module",
        "runpy.run_path",
    }
)
# - repo-relative path to the reason importing it would not say the same thing
ALLOWED = {
    "scripts/benchmarks/llamacpp/benchmark_speedbench.py": "an external speed-bench script, loaded by path",
    "scripts/benchmarks/tts_engines/resident.py": "piper runs from a framework directory placed on sys.path at launch",
    "scripts/config/comfyui/verify_node.py": "the installed node is loaded by path, the way ComfyUI loads it",
    "scripts/tests/cases/shared/gate/test_bat_launchers.py": "the check imports every module a batch file names",
    "scripts/tests/cases/shared/gate/test_manual_entry.py": (
        "executes both entry points the way -m does, so the refusal is tested, not the helper"
    ),
    "scripts/tests/model_run.py": "the dry run imports the module named on the command line",
    "scripts/tests/registry.py": "discovers each test class from its file, then imports the name the path gives",
    "scripts/tests/cases/shared/regression/test_boundaries.py": (
        "checks the source scan against what importing the module defines"
    ),
}


def _dotted(node: ast.expr) -> str:
    """`importlib.import_module` out of the call's target, so one string can match the loader table."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def issues(path: Path) -> list[str]:
    """Every dynamic module load in one file, unless the file is exempt with a stated reason."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name in LOADERS:
            found.append(f"{display_path(path)}:{node.lineno}: dynamic import ({name})")
    return found


def main(argv: list[str] | None = None) -> int:
    files = check_targets(argv, (".py",))
    exempt = [path for path in files if path.relative_to(project_cfg.BASE_DIR).as_posix() in ALLOWED]
    found = [issue for path in files if path not in exempt for issue in issues(path)]
    if not found:
        print(f"[OK] Dynamic imports: {len(files)} files, {len(exempt)} exempt, 0 issues")
        return 0
    for issue in found[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    print(f"[FAIL] Dynamic imports: {len(found)} issue(s) in {len(files)} files")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
