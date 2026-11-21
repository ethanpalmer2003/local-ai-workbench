"""List the local work this repository carries outside git, so a reader can review all of it in one place.

A fix whose code upstream moved, a saved patch nobody reapplied, or an uncommitted edit in a checkout is work
that only exists on this machine. Run `python -m scripts.tools.local_work` to see each one with its state.
"""

import json
import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks.llamacpp.hrx import fixes

ARCHIVE = Path("scripts/download/frameworks/llamacpp/hrx/local-work")
CHECKOUTS = ("llama.cpp", "hrx-system", "rocm-systems")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def checkout_rows() -> list[tuple[str, str, str, str]]:
    """One row per HRX checkout: head, uncommitted files, and commits no remote has."""
    root = project_cfg.FRAMEWORKS_DIR / "llamacpp" / "additions" / "hrx"
    rows = []
    for name in CHECKOUTS:
        directory = root / name
        head = git(directory, "log", "-1", "--format=%h %ad", "--date=short").strip()
        dirty = len([line for line in git(directory, "status", "--porcelain").splitlines() if line])
        branches = []
        for branch in git(directory, "for-each-ref", "--format=%(refname:short)", "refs/heads").split():
            count = len(git(directory, "log", "--oneline", branch, "--not", "--remotes").splitlines())
            if count:
                branches.append(f"{branch}: {count}")
        rows.append((name, head, str(dirty), ", ".join(branches) or "none"))
    return rows


def archive_rows() -> tuple[list[tuple[str, int, str]], list[dict[str, object]]]:
    """The saved patches, with how many commits each one carries, and the manifest."""
    rows = []
    for patch in sorted(ARCHIVE.glob("*.patch")):
        subjects = [
            line
            for line in patch.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("Subject:")
        ]
        rows.append((patch.name, len(subjects), f"{len(subjects)} commit(s)"))
    manifest = ARCHIVE / "manifest.json"
    recorded = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else []
    return rows, recorded


def main() -> int:
    print("=== FIX REGISTRY ===")
    for row in fixes.table():
        print("\t".join(row))
    print("\n=== SAVED LOCAL WORK (tracked) ===")
    rows, manifest = archive_rows()
    for name, count, detail in rows:
        print(f"{name}\t{count} commit(s)\t{ARCHIVE}")
    print(f"{len(manifest)} manifest entries record which commits upstream already carries")
    print("\n=== HRX CHECKOUTS ===")
    for row in checkout_rows():
        print("\t".join(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
