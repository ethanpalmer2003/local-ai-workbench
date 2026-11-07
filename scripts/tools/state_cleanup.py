"""Prune regenerable state: orphaned temp extractions, aborted downloads, old logs."""

import argparse
import shutil
import time
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg


def _size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def prune(pattern: str, root: Path, cutoff: float, dry_run: bool) -> tuple[int, int]:
    """Remove entries under `root` matching `pattern` whose mtime is older than `cutoff`."""
    if not root.is_dir():
        return 0, 0
    count = freed = 0
    for path in root.rglob(pattern):
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        size = _size(path)
        if not dry_run:
            try:
                _remove(path)
            except OSError:
                continue
        count += 1
        freed += size
    return count, freed


def prune_generated(days: int, log_days: int, dry_run: bool) -> list[str]:
    now = time.time()
    cutoff = now - days * 86400
    log_cutoff = now - log_days * 86400
    downloads = project_cfg.STATE_DIR / "downloads"
    report: list[str] = []
    for label, pattern, root, when in (
        ("orphaned _MEI extractions", "_MEI*", cfg.LAUNCH.temp_dir, cutoff),
        ("aborted download blobs", "*.incomplete", downloads, cutoff),
        ("stale download locks", "*.lock", downloads, cutoff),
        ("old run logs", "*.log", project_cfg.LOGS_DIR, log_cutoff),
    ):
        count, freed = prune(pattern, root, when, dry_run)
        if count:
            report.append(f"{label}: {count} item(s), {freed / 1e6:.1f} MB")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Age before temp/download leftovers are pruned.")
    parser.add_argument("--log-days", type=int, default=30, help="Age before run logs are pruned.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be removed.")
    args = parser.parse_args()
    report = prune_generated(args.days, args.log_days, args.dry_run)
    if not report:
        print("[OK] Nothing to prune")
        return 0
    for line in report:
        print(f"{'[WOULD REMOVE]' if args.dry_run else '[REMOVED]'} {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
