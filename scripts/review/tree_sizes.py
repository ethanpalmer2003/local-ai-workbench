"""Say which local trees are expensive and whether git ignores them, since the agent guard reads those files.

The default pass is instant: it lists every top-level tree plus the large sub-trees and asks git which ones it
ignores, which is the same answer the guard derives from `.gitignore` and `scripts/.gitignore`. `--measure`
adds sizes and file counts from the inventory's one-pass walk, so both tools report the same figures.
"""

import argparse
import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review.checks import inventory_code

# - sub-trees a single top-level row would hide
LARGE_SUBTREES = ("scripts/state", "scripts/tests/output", "scripts/benchmarks/output")
# - below this a tree costs a scan nothing, so leaving it uncovered is not a finding
EXPENSIVE_BYTES = 500_000_000
EXPENSIVE_FILES = 20_000


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


def measure(root: Path) -> tuple[int, int]:
    """Return file count and bytes under `root` from the inventory's one-pass walk."""
    return inventory_code.tree_totals(root)


def main(arguments: list[str] | None = None) -> int:
    """Print one row per tree: whether git ignores it always, sizes when asked; exit 1 on a large unignored tree."""
    parser = argparse.ArgumentParser(description="List local trees and check their exclusions.")
    parser.add_argument("--measure", action="store_true", help="add sizes and file counts, which takes a pass")
    options = parser.parse_args(arguments)
    roots = _roots()
    ignored_paths = ignored(roots)
    status = 0
    for root in sorted(roots):
        # - `scripts` itself is tracked, but three ignored run trees sit inside it, so it is covered
        covered = root in ignored_paths or any(
            (project_cfg.BASE_DIR / item).is_relative_to(root) for item in LARGE_SUBTREES
        )
        row = f"ignored={covered!s:5}  {root.relative_to(project_cfg.BASE_DIR)}"
        if options.measure:
            files, size = measure(root)
            row = f"{size / 1_000_000_000:8.2f} GB {files:8d} files  {row}"
            expensive = size >= EXPENSIVE_BYTES or files >= EXPENSIVE_FILES
            if expensive and not covered:
                print(f"[WARN] {root.name} is expensive and not ignored")
                status = 1
        print(row)
    return status


def _roots() -> list[Path]:
    """Every top-level tree except `.git`, plus the large sub-trees a top-level row would hide."""
    roots = [path for path in project_cfg.BASE_DIR.iterdir() if path.is_dir() and not path.name.startswith(".git")]
    roots.extend(path for path in (project_cfg.BASE_DIR / item for item in LARGE_SUBTREES) if path.is_dir())
    return roots


if __name__ == "__main__":
    raise SystemExit(main())
