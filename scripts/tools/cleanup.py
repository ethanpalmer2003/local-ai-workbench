"""Clean the local trees: run evidence, the state logs the runner writes, and the trash itself.

`python -m scripts.tools.cleanup --dry-run` says what would move; `--apply` moves it. Run evidence keeps the
newest run per case and outcome and anything a tracked file cites, so a superseded run leaves while the
evidence behind a written decision stays. Nothing here deletes: output and state move to `trash/<date>/`,
and emptying the trash is a separate, explicit flag.
"""

import argparse
import os
import re
import shutil
import stat
from datetime import date, datetime
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review.lists.sources import tracked_files
from scripts.shared.tables import render_table
from scripts.tools import state_cleanup

# - the two evidence roots, and the run-directory name shape they both use
OUTPUT_ROOTS = (project_cfg.TESTS_DIR / "output", project_cfg.SCRIPTS_DIR / "benchmarks" / "output")
TRASH_DIR = project_cfg.BASE_DIR / "trash"
MAX_DEPTH = 6
# - a run that took minutes to produce keeps more history than one that took seconds: a benchmark or a
#   live probe is expensive to repeat, while a fast suite run is cheap
EXPENSIVE = ("benchmarks/output", "tests/output/probes")
EXPENSIVE_KEEP, EXPENSIVE_DAYS = 5, 90
CHEAP_KEEP, CHEAP_DAYS = 1, 7
# - a suite writes a run per invocation, so an area needs a ceiling of its own
MAX_RUNS_PER_AREA = 20


def run_directories(root: Path) -> list[Path]:
    """Every run directory under `root`: a leaf named with an epoch stamp, at most six levels down."""
    found: list[Path] = []
    for path in _walk(root, MAX_DEPTH):
        if path.name.isdigit() and len(path.name) >= 15 and any(path.iterdir()):
            found.append(path)
    return found


def group_of(run: Path) -> Path:
    """The case and outcome a run belongs to, which is its parent directory."""
    return run.parent


def cited_runs() -> set[str]:
    """The run ids a tracked file names, so the evidence behind a written decision is kept."""
    cited: set[str] = set()
    for path in tracked_files():
        if path.suffix not in {".md", ".py", ".json", ".yaml", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        cited.update(re.findall(r"\b1\d{16,19}\b", text))
    return cited


def superseded(
    runs: list[Path], cited: set[str], *, keep: int | None = None, older_days: int | None = None
) -> list[Path]:
    """Runs to move: superseded within their cost class, old enough, and not cited by a tracked file."""
    by_group: dict[Path, list[Path]] = {}
    for run in runs:
        by_group.setdefault(group_of(run), []).append(run)
    stale: list[Path] = []
    for group in by_group.values():
        ordered = sorted(group, key=lambda path: path.name, reverse=True)
        expensive = _expensive(ordered[0])
        kept = keep if keep is not None else (EXPENSIVE_KEEP if expensive else CHEAP_KEEP)
        age = older_days if older_days is not None else (EXPENSIVE_DAYS if expensive else CHEAP_DAYS)
        for run in ordered[kept:]:
            if run.name in cited or _age_days(run) <= age:
                continue
            stale.append(run)
    return [*stale, *_over_area_cap(runs, cited)]


def _over_area_cap(runs: list[Path], cited: set[str]) -> list[Path]:
    """Runs beyond the per-area ceiling, newest kept first, with a cited run never dropped."""
    by_area: dict[str, list[Path]] = {}
    for run in runs:
        by_area.setdefault(_area_of(run), []).append(run)
    extra: list[Path] = []
    for area in by_area.values():
        ordered = sorted(area, key=lambda path: path.name, reverse=True)
        extra.extend(run for run in ordered[MAX_RUNS_PER_AREA:] if run.name not in cited)
    return extra


def _area_of(run: Path) -> str:
    """The area and case a run belongs to, read from the evidence root rather than by depth."""
    for root in OUTPUT_ROOTS:
        try:
            parts = run.relative_to(root).parts
        except ValueError:
            continue
        return "/".join(parts[:2])
    return "/".join(run.parts[-5:-3])


def _expensive(run: Path) -> bool:
    """Whether this run came from a benchmark or a live probe, which costs time to repeat."""
    try:
        relative = str(run.relative_to(project_cfg.BASE_DIR)).replace("\\", "/")
    except ValueError:
        relative = str(run).replace("\\", "/")
    return any(relative.startswith(item) or item in relative for item in EXPENSIVE)


def _age_days(path: Path) -> int:
    """Whole days since the run directory last changed; a vanished run counts as stale."""
    try:
        changed = path.stat().st_mtime
    except OSError:
        return 10**6
    return (datetime.now() - datetime.fromtimestamp(changed)).days


def move_to_trash(paths: list[Path], stamp: str, dry_run: bool) -> int:
    """Move each path under `trash/<stamp>/cleanup/`, keeping its relative place; return how many moved."""
    moved = 0
    for path in paths:
        target = TRASH_DIR / stamp / "cleanup" / path.relative_to(project_cfg.BASE_DIR)
        if dry_run:
            print(f"[WOULD MOVE] {path} -> {target}")
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        except OSError:
            # - a suite may be writing or removing a run while cleanup works
            continue
        moved += 1
    return moved


def trash_days() -> list[tuple[Path, int]]:
    """Each dated trash folder and the bytes it holds, newest first."""
    days: list[tuple[Path, int]] = []
    if not TRASH_DIR.is_dir():
        return days
    for folder in sorted(TRASH_DIR.iterdir(), reverse=True):
        if folder.is_dir() and folder.name[:10].count("-") == 2:
            days.append((folder, state_cleanup.path_size(folder)))
    return days


def remove_readonly(function, path: str, _error) -> None:
    """Retry a removal a read-only file refused, which a moved git checkout leaves behind.

    A `.git/objects` entry is read-only, and a test run's temp tree keeps one, so a plain `rmtree` stops
    on it with `WinError 5` and leaves the rest of the trash folder in place.
    """
    os.chmod(path, stat.S_IWRITE)
    function(path)


def expired_days(older_than: int) -> list[tuple[Path, int]]:
    """Dated folders old enough to delete; `empty_trash` and its dry run share the one age rule."""
    today = date.today()
    expired: list[tuple[Path, int]] = []
    for folder, size in trash_days():
        try:
            day = datetime.strptime(folder.name[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - day).days >= older_than:
            expired.append((folder, size))
    return expired


def empty_trash(older_than: int) -> int:
    """Delete dated trash folders older than `older_than` days; this is the only deletion in the tool."""
    removed = 0
    for folder, _ in expired_days(older_than):
        shutil.rmtree(folder, onexc=remove_readonly)
        removed += 1
    return removed


def prune_outputs(dry_run: bool) -> tuple[int, float]:
    """Move superseded run evidence to trash; returns the count and the bytes it covers."""
    runs = [run for root in OUTPUT_ROOTS if root.is_dir() for run in run_directories(root)]
    if not runs:
        return 0, 0.0
    cited = cited_runs()
    stale = superseded(runs, cited)
    if not stale:
        return 0, 0.0
    freed = 0
    for run in stale:
        freed += sum(item.stat().st_size for item in run.rglob("*") if item.is_file())
    move_to_trash(stale, date.today().isoformat(), dry_run)
    return len(stale), freed


def main(arguments: list[str] | None = None) -> int:
    """Report or perform the cleanup; without a selector it reports every tree and changes nothing."""
    parser = argparse.ArgumentParser(description="Prune superseded run evidence, state logs and the trash.")
    parser.add_argument("--outputs", action="store_true", help="move superseded runs out of the evidence roots")
    parser.add_argument("--state", action="store_true", help="prune old state logs through state_cleanup")
    parser.add_argument("--keep", type=int, help="runs to keep per case, overriding the cost class")
    parser.add_argument("--older-than", type=int, help="age floor in days, overriding the cost class")
    parser.add_argument("--empty-trash", type=int, metavar="DAYS", help="delete dated trash folders older than DAYS")
    parser.add_argument("--dry-run", action="store_true", help="report without moving or deleting")
    parser.add_argument("--apply", action="store_true", help="carry the changes out")
    options = parser.parse_args(arguments)
    if not options.apply and not options.dry_run:
        options.dry_run = True
    if options.dry_run and options.apply:
        parser.error("choose --dry-run or --apply, not both")
    selected = options.outputs or options.state or options.empty_trash is not None
    if not selected:
        print("nothing selected; pass --outputs, --state or --empty-trash DAYS")
        days = [(str(folder), f"{size / 1_000_000_000:.2f} GB") for folder, size in trash_days()[:10]]
        if days:
            print(render_table(days, ("trash day", "size")))
        return 0
    date.today().isoformat()
    status = 0
    if options.outputs:
        count, freed = prune_outputs(options.dry_run)
        print(f"{count} superseded run(s), {freed / 1e6:.1f} MB")
    if options.state:
        state_cleanup.prune_generated(7, 30, 30, options.dry_run)
    if options.empty_trash is not None:
        status |= _empty(options.empty_trash, options.dry_run)
    return status


def _empty(older_than: int, dry_run: bool) -> int:
    """Report or delete the dated trash folders older than `older_than` days."""
    if dry_run:
        days = [(str(folder), f"{size / 1_000_000_000:.2f} GB") for folder, size in expired_days(older_than)]
        if days:
            print(render_table(days, ("trash day", "size")))
        else:
            print(f"no dated trash folder is {older_than} day(s) old or more")
        return 0
    print(f"deleted {empty_trash(older_than)} dated trash folder(s)")
    return 0


def _report(moved: int, planned: int, dry_run: bool) -> int:
    if dry_run:
        print(f"{planned} run(s) would move")
    else:
        print(f"{moved} run(s) moved")
    return 0


def _walk(root: Path, depth: int):
    """Yield every directory under `root`, stopping at `depth` levels."""
    if depth <= 0 or not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            yield entry
            yield from _walk(entry, depth - 1)


if __name__ == "__main__":
    raise SystemExit(main())
