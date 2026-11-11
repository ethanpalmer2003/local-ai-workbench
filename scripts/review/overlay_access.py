"""Only the overlay module resolves local input paths; a direct read anywhere else fails the gate."""

import argparse
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import sources

OWNER = "scripts/config/local_overlay.py"
DECLARES_PATHS = "scripts/config/project_config.py"
# - the check names the patterns it looks for, and the overlay test sets the variables on purpose
SELF_REFERENTIAL = {OWNER, "scripts/review/overlay_access.py", "scripts/tests/cases/shared/test_local_overlay.py"}
ENV_READS = ("AI_INPUT_DIR", "AI_VOICES_DIR")
ATTRIBUTE_READS = (".INPUT_DIR", ".VOICES_DIR")


def issues(root: Path | None = None, paths: list[Path] | None = None) -> list[str]:
    """Tracked modules that resolve an overlay path without going through the owner module."""
    base = root or project_cfg.BASE_DIR
    found = []
    for entry in paths if paths is not None else sources.tracked_files():
        path = entry.as_posix()
        if not path.startswith("scripts/") or not path.endswith(".py"):
            continue
        if path in SELF_REFERENTIAL or path == DECLARES_PATHS:
            continue
        text = (base / entry).read_text(encoding="utf-8", errors="ignore")
        for name in ENV_READS:
            if f'"{name}"' in text or f"'{name}'" in text:
                found.append(f"{path}: reads {name}; call local_overlay instead")
        for attribute in ATTRIBUTE_READS:
            if attribute in text:
                found.append(f"{path}: reads {attribute} directly; call local_overlay instead")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    found = issues()
    for issue in found:
        print(f"[FAIL] {issue}")
    if not found:
        print("[OK] Overlay paths resolve in one module")
    return int(bool(found))


if __name__ == "__main__":
    raise SystemExit(main())
