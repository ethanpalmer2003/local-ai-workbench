"""Prune regenerable state: orphaned temp extractions, aborted downloads, old logs.

Everything here is an artifact a run rewrites from a source of truth, so it is deleted rather than moved to
trash. Evidence a tracked file cites, and anything moved out of a tree, belongs to
[cleanup](cleanup.py), which moves it and owns deleting the trash.
"""

import argparse
import os
import shutil
import time
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg


def path_size(path: Path) -> int:
    """Bytes a file or a folder tree holds, from one scandir pass; an unreadable entry counts as zero."""
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    pending = [path]
    while pending:
        try:
            entries = list(os.scandir(pending.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
            except OSError:
                continue
    return total


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        # - a running service keeps its log open; leave it for the next prune instead of failing the gate
        return


# - the current update and the last working one are all a repair needs
KEEP_UPDATES = 2
# - the same shape for the gate history: the latest run and the one before it
KEEP_REVIEW_LOGS = 2
# - every other log area keeps the latest entry and the one before it
KEEP_LOG_ENTRIES = 2
# - a PyInstaller extraction lasts one launch, so the count bound matters more than its age; a young one is
#   never touched because a running child may still own it
KEEP_EXTRACTIONS = 20
MIN_EXTRACTION_AGE_HOURS = 24
# - handled by their own rules above
SPECIAL_LOG_AREAS = frozenset({"shared/review", "shared/framework_updates"})


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
        size = path_size(path)
        if not dry_run:
            try:
                _remove(path)
            except OSError:
                continue
        count += 1
        freed += size
    return count, freed


def prune_update_logs(dry_run: bool) -> tuple[int, int]:
    """Keep the two newest framework updates: the current one and the last working one."""
    root = project_cfg.component("shared").logs_dir / "framework_updates"
    if not root.is_dir():
        return 0, 0
    folders = sorted(path for path in root.iterdir() if path.is_dir())
    legacy = sorted(path for path in root.iterdir() if path.is_file())
    stale = [*folders[:-KEEP_UPDATES], *legacy[:-KEEP_UPDATES]]
    count = freed = 0
    for path in stale:
        size = path_size(path)
        if not dry_run:
            _remove(path)
        count += 1
        freed += size
    return count, freed


def prune_extractions(
    root: Path, dry_run: bool, keep: int = KEEP_EXTRACTIONS, min_age_hours: float = MIN_EXTRACTION_AGE_HOURS
) -> tuple[int, int]:
    """Keep the newest few `_MEI*` extractions: one belongs to a launch, and the rest are debris."""
    if not root.is_dir():
        return 0, 0
    # - ties break by name: extraction folders created in one second keep a stable order
    entries = sorted(root.glob("_MEI*"), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    youngest = time.time() - min_age_hours * 3600
    count = freed = 0
    for path in entries[keep:]:
        try:
            if path.stat().st_mtime >= youngest:
                continue
        except OSError:
            continue
        size = path_size(path)
        if not dry_run:
            try:
                _remove(path)
            except OSError:
                continue
        count += 1
        freed += size
    return count, freed


def prune_review_reports(dry_run: bool) -> tuple[int, int]:
    """Keep the latest gate report and the one before it, in the tree the gate writes them to."""
    root = project_cfg.component("shared").generated_dir / "code_review"
    if not root.is_dir():
        return 0, 0
    folders = sorted(path for path in root.iterdir() if path.is_dir())
    count = freed = 0
    for path in folders[:-KEEP_REVIEW_LOGS]:
        size = path_size(path)
        if not dry_run:
            _remove(path)
        count += 1
        freed += size
    return count, freed


def prune_launch_cache(cutoff: float, dry_run: bool) -> tuple[int, int]:
    """Drop launch scratch entries past the age floor; the directory refills on demand."""
    root = cfg.LAUNCH.temp_dir
    if not root.is_dir():
        return 0, 0
    count = freed = 0
    for path in root.iterdir():
        if path.name.startswith("_MEI"):
            continue
        try:
            age = path.stat().st_mtime
        except OSError:
            continue
        if age >= cutoff:
            continue
        size = path_size(path)
        if not dry_run:
            _remove(path)
        count += 1
        freed += size
    return count, freed


def prune_review_logs(dry_run: bool) -> tuple[int, int]:
    """Keep the latest gate runs and the one before them; older timings are history nobody reads."""
    root = project_cfg.LOGS_DIR / "shared" / "review"
    if not root.is_dir():
        return 0, 0
    logs = sorted(root.glob("*.json"))
    count = freed = 0
    for path in logs[:-KEEP_REVIEW_LOGS]:
        size = path_size(path)
        if not dry_run:
            _remove(path)
        count += 1
        freed += size
    return count, freed


def prune_log_areas(dry_run: bool) -> tuple[int, int]:
    """Keep the two newest entries in each log area, so a per-run log cannot pile up."""
    root = project_cfg.LOGS_DIR
    count = freed = 0
    for area in [root, *(path for path in root.rglob("*") if path.is_dir())]:
        relative = str(area.relative_to(root)).replace("\\\\", "/")
        if any(relative == special or relative.startswith(special + "/") for special in SPECIAL_LOG_AREAS):
            continue
        if len(area.relative_to(root).parts) > 4 or not any(entry.is_file() for entry in area.iterdir()):
            continue
        entries = [*area.glob("*")]
        files = [entry for entry in entries if entry.is_file()]
        stale = stale_entries(files, KEEP_LOG_ENTRIES)
        for path in stale:
            size = path_size(path)
            if not dry_run:
                _remove(path)
            count += 1
            freed += size
    builds = root / "framework-builds"
    if builds.is_dir():
        for path in stale_entries([*builds.glob("*")], KEEP_LOG_ENTRIES):
            size = path_size(path)
            if not dry_run:
                _remove(path)
            count += 1
            freed += size
    return count, freed


def stale_entries(entries: list[Path], keep: int) -> list[Path]:
    """Everything but the newest `keep` entries, ordered by name because a run name is a stamp."""
    ordered = sorted(entries, key=lambda path: path.name)
    return ordered[:-keep] if keep else ordered


def _prune_suite_runs(cutoff: float, dry_run: bool) -> tuple[int, int]:
    """Suite runs land under state/temp/runs rather than the evidence root, so the ordinary window applies."""
    run_root = project_cfg.STATE_DIR / "temp" / "runs"
    count = freed = 0
    for folder in run_root.glob("*/*") if run_root.is_dir() else ():
        folder_count, folder_freed = prune("*", folder, cutoff, dry_run, recursive=False)
        count += folder_count
        freed += folder_freed
    return count, freed


def prune_generated(days: int, log_days: int, cache_days: int, dry_run: bool) -> list[str]:
    """Prune every regenerable tree this workspace writes, one line per owner that had work."""
    now = time.time()
    cutoff = now - days * 86400
    log_cutoff = now - log_days * 86400
    cache_cutoff = now - cache_days * 86400
    downloads = project_cfg.STATE_DIR / "downloads"
    steps: tuple[tuple[str, tuple[int, float]], ...] = (
        ("old run logs", prune("*.log", project_cfg.LOGS_DIR, log_cutoff, dry_run)),
        ("aborted download blobs", prune("*.incomplete", downloads, cutoff, dry_run)),
        ("stale download locks", prune("*.lock", downloads, cutoff, dry_run)),
        # - the framework fills this model cache on demand, so its hashed folders are the unit and a
        #   re-download is the cost; the longer window keeps a repeated comparison warm
        ("old suite run folders", _prune_suite_runs(cutoff, dry_run)),
        ("old area logs", prune_log_areas(dry_run)),
        ("old gate runs", prune_review_logs(dry_run)),
        ("old gate reports", prune_review_reports(dry_run)),
        ("old launch scratch entries", prune_launch_cache(cache_cutoff, dry_run)),
        ("surplus launch extractions", prune_extractions(cfg.LAUNCH.temp_dir, dry_run)),
        ("old framework updates", prune_update_logs(dry_run)),
        ("old AudioCpp support-model caches", prune("*", cfg.LAUNCH.temp_dir / "audiocpp-gguf", cache_cutoff, dry_run)),
    )
    return [f"{label}: {count} item(s), {freed / 1e6:.1f} MB" for label, (count, freed) in steps if count]


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
