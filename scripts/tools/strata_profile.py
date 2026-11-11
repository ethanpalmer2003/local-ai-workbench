"""Keep Strata's profile folders as junctions into the workspace state tree.

A full installer run can replace the junctions with real folders in the profile. The default
mode reports the three possible states; `--fix` moves a real folder back into state and recreates
the junction. Stop the app first; the script refuses to move files while it runs.
"""

import argparse
import os
import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg

LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
PAIRS = {"Strata": "desktop", "ai.strata.desktop": "webview"}


def expected(name: str) -> Path:
    return project_cfg.STATE_DIR / "strata" / PAIRS[name]


def state(name: str) -> str:
    """junction, real, missing, or wrong-target for one profile folder."""
    link = LOCAL / name
    if not link.exists():
        return "missing"
    if link.is_junction():
        return "junction" if link.resolve() == expected(name).resolve() else "wrong-target"
    return "real"


def _merge(source: Path, target: Path) -> None:
    """Move every child into target, replacing same-named files."""
    target.mkdir(parents=True, exist_ok=True)
    for item in list(source.iterdir()):
        destination = target / item.name
        if item.is_dir() and not item.is_symlink():
            _merge(item, destination)
        elif destination.exists():
            destination.unlink()
            item.replace(destination)
        else:
            item.replace(destination)
    source.rmdir()


def repair(name: str) -> str:
    link = LOCAL / name
    target = expected(name)
    target.mkdir(parents=True, exist_ok=True)
    if link.is_junction():
        if link.resolve() == target.resolve():
            return "junction"
        link.unlink()
    elif link.exists():
        _merge(link, target)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    return "junction"


def running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq strata-desktop.exe", "/NH"], capture_output=True, text=True, check=False
    )
    return "strata-desktop.exe" in result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="move real folders back into state and recreate junctions")
    args = parser.parse_args(argv)
    states = {name: state(name) for name in PAIRS}
    for name, value in states.items():
        print(f"[{'OK' if value == 'junction' else 'WARN'}] {LOCAL / name} -> {value}")
    if all(value == "junction" for value in states.values()):
        print("[OK] Strata profile folders are junctions into state")
        return 0
    if not args.fix:
        print("[WARN] run with --fix to relocate them, after closing the Strata app")
        return 1
    if running():
        print("[FAIL] Close the Strata app before moving its profile folders")
        return 1
    for name in PAIRS:
        if states[name] != "junction":
            print(f"[FIX] {name} -> {repair(name)}")
    print("[OK] Strata profile folders are junctions into state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
