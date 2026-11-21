"""Reapply the local HRX fixes, and say which upstream has already made unnecessary.

Each fix is a small patch against one HRX checkout plus a marker that proves the fix is present. After an
upstream merge the check reports one of three states: `applied` when the marker is in the tree, `needed` when
the patch still applies, and `drifted` when the code moved and a person has to decide whether the fix is still
required. `ensure()` runs inside the build so an update reapplies what is still needed without a reminder.
"""

import argparse
import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import update_shared as updater

FIXES_DIR = Path(__file__).with_name("fixes")
RECORDS_PATH = FIXES_DIR / "fixes.json"


class FixState(str, Enum):
    APPLIED = "applied"
    NEEDED = "needed"
    DRIFTED = "drifted"


@dataclass(frozen=True)
class Fix:
    identity: str
    repository: str
    marker_file: str
    marker: str
    patch: Path
    reason: str


def roots() -> dict[str, Path]:
    """The three checkouts a fix can touch."""
    from scripts.download.frameworks.framework_catalog import hrx_tools

    return {tool.name.rsplit("/", 1)[-1]: project_cfg.FRAMEWORKS_DIR / tool.name for tool in hrx_tools()}


def records() -> tuple[Fix, ...]:
    raw = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
    return tuple(
        Fix(
            identity=str(item["id"]),
            repository=str(item["repository"]),
            marker_file=str(item["marker_file"]),
            marker=str(item["marker"]),
            patch=FIXES_DIR / str(item["patch"]),
            reason=str(item["reason"]),
        )
        for item in raw
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def state(fix: Fix) -> FixState:
    """`applied` by marker, else `needed` when the patch applies, else `drifted`."""
    root = roots().get(fix.repository)
    if root is None:
        raise updater.UpdateError(f"Fix {fix.identity} names an unknown repository: {fix.repository}")
    marker_path = root / fix.marker_file
    if marker_path.is_file() and fix.marker in marker_path.read_text(encoding="utf-8", errors="replace"):
        return FixState.APPLIED
    if _git(root, "apply", "--check", str(fix.patch)).returncode == 0:
        return FixState.NEEDED
    return FixState.DRIFTED


def apply(fix: Fix) -> None:
    root = roots()[fix.repository]
    result = _git(root, "apply", str(fix.patch))
    if result.returncode != 0:
        raise updater.UpdateError(f"Fix {fix.identity} failed to apply: {result.stderr.strip()}")


def ensure() -> int:
    """Apply every fix that is still needed; return the count that could not be applied."""
    failures = 0
    for fix in records():
        current = state(fix)
        if current is FixState.APPLIED:
            print(f"[OK] fix {fix.identity}: already present")
        elif current is FixState.NEEDED:
            try:
                apply(fix)
            except updater.UpdateError as error:
                print(f"[FAIL] fix {fix.identity}: {error}")
                failures += 1
            else:
                print(f"[OK] fix {fix.identity}: reapplied")
        else:
            print(
                f"[WARN] fix {fix.identity}: the patch no longer applies, so upstream changed "
                f"{fix.marker_file}; check whether the fix is still needed. Why: {fix.reason}"
            )
    return failures


def table() -> list[tuple[str, str, str, str]]:
    rows = []
    for fix in records():
        rows.append((fix.identity, fix.repository, state(fix).value, fix.reason))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="reapply every fix that is still needed")
    args = parser.parse_args()
    for identity, repository, current, reason in table():
        print(f"{identity}\t{repository}\t{current}\t{reason}")
    if not args.apply:
        return 0
    return 1 if ensure() else 0


if __name__ == "__main__":
    raise SystemExit(main())
