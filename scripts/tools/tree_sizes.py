"""Say which local trees are expensive and whether the ignore files and the agent guard cover them.

The default pass is instant: it lists every top-level tree plus the large sub-trees, asks git which ones it
ignores, and reads the guard plugin's list. `--measure` adds sizes and file counts through `robocopy /L`, a
single C-level pass, which is faster than walking the tree from Python.
"""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from scripts.config import project_config as project_cfg

# - the profile bundle keeps its list here; the workspace copy is the source it installs from
GUARD_PLUGIN = Path.home() / ".dsh" / "bundles" / "guard-deep-scan" / "index.js"
GUARD_SOURCE = project_cfg.BASE_DIR / "scripts/state/plugins/guard-deep-scan/index.js"
# - sub-trees a single top-level row would hide
LARGE_SUBTREES = ("scripts/state", "scripts/tests/output", "scripts/benchmarks/output")


def ignored(paths: list[Path]) -> set[Path]:
    """Ask git which of these paths it ignores, in one call."""
    if not paths:
        return set()
    relative = [str(path.relative_to(project_cfg.BASE_DIR)).replace("\\", "/") for path in paths]
    # - NUL separators, because text-mode input would turn LF into CRLF and change every path
    result = subprocess.run(
        ["git", "-C", str(project_cfg.BASE_DIR), "check-ignore", "--stdin", "-z"],
        input=("\0".join(relative) + "\0").encode(),
        capture_output=True,
        check=False,
    )
    matched = result.stdout.decode("utf-8", errors="replace").split("\0")
    return {project_cfg.BASE_DIR / item.strip() for item in matched if item.strip()}


def guarded(plugin: Path) -> tuple[set[str], set[str]]:
    """Read the guard's segment names and relative tree paths, or nothing when it is not installed."""
    if not plugin.is_file():
        return set(), set()
    source = plugin.read_text(encoding="utf-8")
    segment = re.search(r"HEAVY_SEGMENTS = \[(.*?)\];", source, re.S)
    trees = re.search(r"HEAVY_TREES = \[(.*?)\];", source, re.S)
    names = set(re.findall(r"'([^']+)'", segment.group(1))) if segment else set()
    paths = set(re.findall(r"'([^']+)'", trees.group(1))) if trees else set()
    return names, paths


def covered(path: Path, segments: set[str], trees: set[str]) -> bool:
    """Whether the guard names this tree, as a path segment or as a relative path suffix."""
    if any(part in segments for part in path.parts):
        return True
    relative = str(path.relative_to(project_cfg.BASE_DIR)).replace("\\", "/").lower()
    return any(relative == name or relative.endswith(f"/{name}") for name in trees)


def measure(root: Path) -> tuple[int, int]:
    """Return file count and bytes under `root` from one robocopy listing, following no links."""
    with tempfile.TemporaryDirectory() as unused:
        result = subprocess.run(
            ["robocopy", str(root), unused, "/L", "/S", "/BYTES", "/NC", "/NFL", "/NDL", "/NJH", "/XJ"],
            capture_output=True,
            text=True,
            check=False,
        )
    files = re.search(r"^\s*Files :\s+(\d+)", result.stdout, re.MULTILINE)
    size = re.search(r"^\s*Bytes :\s+(\d+)", result.stdout, re.MULTILINE)
    return (int(files.group(1)) if files else 0, int(size.group(1)) if size else 0)


def main(arguments: list[str] | None = None) -> int:
    """Print one row per tree: coverage always, sizes when asked; exit 1 on an uncovered large tree."""
    parser = argparse.ArgumentParser(description="List local trees and check their exclusions.")
    parser.add_argument("--measure", action="store_true", help="add sizes and file counts, which takes a pass")
    parser.add_argument("--plugin", default=str(GUARD_PLUGIN), help="guard plugin source to read the list from")
    options = parser.parse_args(arguments)
    roots = _roots()
    ignored_paths = ignored(roots)
    segments, trees = guarded(Path(options.plugin))
    if not (segments or trees):
        segments, trees = guarded(GUARD_SOURCE)
    status = 0
    for root in sorted(roots):
        git_covers = root in ignored_paths
        guard_covers = covered(root, segments, trees)
        row = f"ignored={git_covers!s:5} guarded={guard_covers!s:5}  {root.relative_to(project_cfg.BASE_DIR)}"
        if options.measure:
            files, size = measure(root)
            row = f"{size / 1_000_000_000:8.2f} GB {files:8d} files  {row}"
            if not git_covers:
                print(f"[WARN] {root.name} is not ignored by git")
                status = 1
            if not guard_covers:
                print(f"[WARN] {root.name} is not in the guard list")
        print(row)
    missing = sorted(name for name in trees if not (project_cfg.BASE_DIR / name).exists())
    for name in missing:
        print(f"[WARN] the guard names {name}, which does not exist")
    return status


def _roots() -> list[Path]:
    """Every top-level tree except `.git`, plus the large sub-trees a top-level row would hide."""
    roots = [path for path in project_cfg.BASE_DIR.iterdir() if path.is_dir() and not path.name.startswith(".git")]
    roots.extend(path for path in (project_cfg.BASE_DIR / item for item in LARGE_SUBTREES) if path.is_dir())
    return roots


if __name__ == "__main__":
    raise SystemExit(main())
