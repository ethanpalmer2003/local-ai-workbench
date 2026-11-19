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


# - the current update and the last working one are all a repair needs
KEEP_UPDATES = 2


def prune(pattern: str, root: Path, cutoff: float, dry_run: bool, recursive: bool = True) -> tuple[int, int]:
    """Remove entries under `root` matching `pattern` whose mtime is older than `cutoff`."""
    if not root.is_dir():
        return 0, 0
    count = freed = 0
    for path in root.rglob(pattern) if recursive else root.glob(pattern):
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


def prune_update_logs(cutoff: float, dry_run: bool) -> tuple[int, int]:
    """Keep the two newest framework updates: the current one and the last working one."""
    root = project_cfg.component("shared").logs_dir / "framework_updates"
    if not root.is_dir():
        return 0, 0
    folders = sorted(path for path in root.iterdir() if path.is_dir())
    legacy = sorted(path for path in root.iterdir() if path.is_file())
    stale = [*folders[:-KEEP_UPDATES], *legacy[:-KEEP_UPDATES]]
    count = freed = 0
    for path in stale:
        size = _size(path)
        if not dry_run:
            _remove(path)
        count += 1
        freed += size
    return count, freed


def prune_generated(days: int, log_days: int, cache_days: int, dry_run: bool) -> list[str]:
    now = time.time()
    cutoff = now - days * 86400
    log_cutoff = now - log_days * 86400
    cache_cutoff = now - cache_days * 86400
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
    # - the framework fills this model cache on demand, so its hashed folders are the unit and a
    #   re-download is the cost; the longer window keeps a repeated comparison warm
    # - suite runs land here rather than in the evidence root, so the ordinary window is all they get
    run_root = project_cfg.STATE_DIR / "temp" / "runs"
    run_count = run_freed = 0
    for folder in run_root.glob("*/*") if run_root.is_dir() else ():
        count, freed = prune("*", folder, cutoff, dry_run, recursive=False)
        run_count += count
        run_freed += freed
    if run_count:
        report.append(f"old suite run folders: {run_count} item(s), {run_freed / 1e6:.1f} MB")
    update_count, update_freed = prune_update_logs(cutoff, dry_run)
    if update_count:
        report.append(f"old framework updates: {update_count} item(s), {update_freed / 1e6:.1f} MB")
    cache_root = cfg.LAUNCH.temp_dir / "audiocpp-gguf"
    count, freed = prune("*", cache_root, cache_cutoff, dry_run, recursive=False)
    if count:
        report.append(f"old AudioCpp support-model caches: {count} item(s), {freed / 1e6:.1f} MB")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Age before temp/download leftovers are pruned.")
    parser.add_argument("--log-days", type=int, default=30, help="Age before run logs are pruned.")
    parser.add_argument(
        "--cache-days", type=int, default=30, help="Age before AudioCpp support-model caches are pruned."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what would be removed.")
    args = parser.parse_args()
    report = prune_generated(args.days, args.log_days, args.cache_days, args.dry_run)
    if not report:
        print("[OK] Nothing to prune")
        return 0
    for line in report:
        print(f"{'[WOULD REMOVE]' if args.dry_run else '[REMOVED]'} {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
