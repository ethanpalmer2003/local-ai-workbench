"""Check or repair the Low integrity label that DSH workspace-write leaves on the workspace.

The label lives on disk and survives the session, so a normal launch of an `.exe` inside the
workspace runs Low and cannot write Medium locations. Default is a read-only check; `--fix`
restores Medium on the root and the executable-bearing subtrees.
"""

import argparse
import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg

# - data/ holds model weights and needs no launch; the rest can carry executables
SUBTREES = ("frameworks", "scripts", "bat", ".agents", "notes", "trash")


def label(path: Path) -> str:
    """The mandatory-label line for one object, or an empty string when it has none."""
    result = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        if "Mandatory Label" in line:
            return line.strip()
    return ""


def is_low(text: str) -> bool:
    return "Low Mandatory Level" in text


def check() -> int:
    found = 0
    targets = [project_cfg.BASE_DIR, *(project_cfg.BASE_DIR / name for name in SUBTREES)]
    for path in targets:
        if not path.exists():
            continue
        text = label(path)
        state = "LOW" if is_low(text) else "medium"
        print(f"[{'WARN' if is_low(text) else 'OK'}] {path} -> {state}")
        found += bool(is_low(text))
    if found:
        print(f"[WARN] {found} object(s) still carry the Low label; run with --fix")
        return 1
    print("[OK] No Low integrity label in the executable-bearing tree")
    return 0


def fix() -> int:
    base = project_cfg.BASE_DIR
    subprocess.run(["icacls", str(base), "/setintegritylevel", "(OI)(CI)Medium"], check=False, capture_output=True)
    for name in SUBTREES:
        path = base / name
        if not path.is_dir():
            continue
        print(f"[FIX] {path}")
        subprocess.run(
            ["icacls", str(path), "/setintegritylevel", "(OI)(CI)Medium", "/T", "/C"], check=False, capture_output=True
        )
    print("[OK] Medium restored on the workspace root and its executable-bearing subtrees")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="restore Medium instead of only reporting")
    args = parser.parse_args(argv)
    return fix() if args.fix else check()


if __name__ == "__main__":
    raise SystemExit(main())
