"""Inspect, locate, add, replace and safely retire model-catalog weights.

- `where LABEL` lists catalog/runtime/workflow/Strata references and source mentions.
- `remove LABEL` is a dry run; `--apply` edits catalog.json, regenerates ids.py,
  moves installed files to C:/AI/trash, and refuses when runtime references remain.
- `replace OLD NEW --apply` rewrites active references, removes the old catalog
  entry, and moves the old weights to trash. Strata native configs are a boundary.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.models import catalog
from scripts.download.models import model_sync


@dataclass(frozen=True)
class Mention:
    path: Path
    line: int
    text: str


def model_for(value: str) -> model_cfg.ModelDownload:
    path = Path(value)
    for model in catalog.load_catalog():
        if model.label == value or model.path == path:
            return model
    raise SystemExit(f"[FAIL] Unknown catalog label or path: {value}")


def path_matches(candidate: Path, model_path: Path) -> bool:
    candidate, target = candidate.resolve(), model_path.resolve()
    if candidate == target:
        return True
    marker = "-00001-of-"
    if marker in target.name:
        prefix = target.name.split(marker, 1)[0]
        return candidate.parent == target.parent and candidate.name.startswith(prefix + "-")
    return False


def references(model: model_cfg.ModelDownload) -> tuple[list[model_sync.ModelReference], list[str]]:
    warnings: list[str] = []
    found = [
        ref
        for ref in (*model_sync.runtime_references(), *model_sync.catalog_references())
        if path_matches(ref.path, model.path)
    ]
    try:
        found.extend(ref for ref in model_sync.strata_references() if path_matches(ref.path, model.path))
    except (OSError, ValueError, KeyError) as error:
        warnings.append(f"Strata references unavailable: {error}")
    return found, warnings


def _excluded(path: Path) -> bool:
    return bool({"output", "old", "retired", "__pycache__"} & set(path.parts))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(project_cfg.BASE_DIR))
    except ValueError:
        return str(path)


def mention_files() -> list[Path]:
    files = set(model_sync.source_files())
    files.update(project_cfg.TEST_CASES_DIR.rglob("*.py"))
    files.update(project_cfg.CONFIG_DIR.rglob("*.md"))
    files.update((project_cfg.BASE_DIR / "notes").rglob("*.md"))
    files.add(project_cfg.BASE_DIR / "README.md")
    return sorted(file for file in files if file.is_file() and not _excluded(file))


def mentions(model: model_cfg.ModelDownload) -> list[Mention]:
    needles = {model.label, model.path.name, model.destination}
    found: list[Mention] = []
    for file in mention_files():
        try:
            lines = file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for number, text in enumerate(lines, 1):
            if any(needle and needle in text for needle in needles):
                found.append(Mention(file, number, text.strip()))
    return found


def blocker_lines(
    model: model_cfg.ModelDownload, refs: list[model_sync.ModelReference], found_mentions: list[Mention]
) -> list[str]:
    catalog_dir = catalog.CATALOG_PATH.parent
    blockers = [
        f"{ref.source}: {ref.path}" for ref in refs if ref.required and not ref.source.startswith("download catalog:")
    ]
    blockers += [
        f"{item.path.relative_to(project_cfg.BASE_DIR)}:{item.line}: {item.text}"
        for item in found_mentions
        if catalog_dir not in item.path.parents
    ]
    return blockers


def entry_json(model: model_cfg.ModelDownload) -> str:
    return json.dumps(catalog.entry_dict(model), indent=2)


def installed_files(model: model_cfg.ModelDownload) -> list[Path]:
    target = model.path
    marker = "-00001-of-"
    if marker not in target.name:
        return [target] if target.is_file() else []
    prefix, _, split = target.name.partition(marker)
    try:
        count = int(split.split(".", 1)[0])
    except ValueError:
        return [target] if target.is_file() else []
    expected = [
        target.with_name(f"{prefix}-{index:05d}-of-{split.split('.', 1)[0]}.gguf") for index in range(1, count + 1)
    ]
    found = [path for path in expected if path.is_file()]
    if found:
        return found
    # - First shard may already be gone; still collect any surviving shards.
    return sorted(target.parent.glob(f"{prefix}-*-of-*.gguf")) if target.parent.is_dir() else []


def trash_target(source: Path, stamp: str) -> Path:
    try:
        relative = source.resolve().relative_to(project_cfg.BASE_DIR)
    except ValueError:
        relative = Path(source.name)
    return project_cfg.BASE_DIR / "trash" / "model_admin" / stamp / relative


def backup_file(source: Path, stamp: str) -> Path | None:
    if not source.is_file():
        return None
    target = trash_target(source, stamp)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    print(f"[BACKUP] {source} -> {target}")
    return target


def move_to_trash(source: Path, stamp: str) -> None:
    target = trash_target(source, stamp)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    print(f"[OK] {source} -> {target}")


def run_model_sync() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.download.models.model_sync"],
        cwd=project_cfg.BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


def print_model(model: model_cfg.ModelDownload) -> None:
    refs, warnings = references(model)
    found_mentions = mentions(model)
    print(f"Label    : {model.label}")
    print(f"Group    : {model.group}")
    print(f"Path     : {model.path} ({'installed' if model.path.is_file() else 'missing'})")
    print(f"Roles    : {', '.join(model.roles) or '-'}")
    print(f"Runtimes : {', '.join(model.runtimes) or '-'}")
    print(f"Catalog  : {'required' if model.in_use else 'inactive'}")
    print("\nReferences:")
    for ref in refs:
        print(f"  {'[REQUIRED]' if ref.required else '[catalog] '} {ref.source}: {ref.path}")
    if found_mentions:
        print("\nSource mentions:")
        for item in found_mentions[:80]:
            print(f"  {display_path(item.path)}:{item.line}: {item.text}")
        if len(found_mentions) > 80:
            print(f"  ... {len(found_mentions) - 80} more")
    blockers = blocker_lines(model, refs, found_mentions)
    if blockers:
        print("\nBlocking references (remove/replace these first):")
        for line in blockers[:80]:
            print(f"  [BLOCK] {line}")
    for warning in warnings:
        print(f"  [WARN] {warning}")
    print(f"\nCatalog source: {catalog.CATALOG_PATH.relative_to(project_cfg.BASE_DIR)}")
    print("Catalog entry:\n" + entry_json(model))


def command_status(model: model_cfg.ModelDownload) -> int:
    print_model(model)
    return 0


def command_remove(model: model_cfg.ModelDownload, apply: bool) -> int:
    refs, _ = references(model)
    blockers = blocker_lines(model, refs, mentions(model))
    files = installed_files(model)
    print(f"Remove {model.label}")
    for file in files:
        print(f"  move -> {trash_target(file, '<run>')}")
    if not files:
        print("  [WARN] No installed file; cleaning the catalog/references only.")
    if blockers:
        print("\n[FAIL] Refusing removal; still referenced:")
        for line in blockers[:80]:
            print(f"  {line}")
        return 1
    if not apply:
        print("\n[Dry run] Re-run with --apply to edit catalog.json and move files to trash.")
        return 0
    stamp = str(time.time_ns())
    home = catalog.entry_home(model.label)
    backup_file(home, stamp)
    removed = catalog.remove_entry(model.label)
    if removed is None:
        print(f"[WARN] {model.label} is not listed in any catalog file; the weights were still retired.")
    else:
        catalog.write_ids()
        print(f"[OK] Removed {model.label} from {display_path(removed)}")
    for file in files:
        move_to_trash(file, stamp)
    return run_model_sync()


def rewrite_files(include_docs: bool, include_tests: bool = False) -> list[Path]:
    files = set(model_sync.source_files())
    if include_tests:
        files.update(project_cfg.TEST_CASES_DIR.rglob("*.py"))
    if include_docs:
        files.update(project_cfg.CONFIG_DIR.rglob("*.md"))
        files.update((project_cfg.BASE_DIR / "notes").rglob("*.md"))
    excluded = {catalog.CATALOG_PATH.resolve(), catalog.IDS_PATH.resolve()}
    return sorted(
        file
        for file in files
        if file.is_file() and not _excluded(file) and file.resolve() not in excluded and "strata" not in file.parts
    )


def replacement_pairs(old: model_cfg.ModelDownload, new: model_cfg.ModelDownload) -> list[tuple[str, str]]:
    pairs = [(old.label, new.label), (str(old.path), str(new.path))]
    if old.filename and new.filename and old.filename != new.filename:
        pairs.append((old.filename, new.filename))
    if old.path.name != new.path.name:
        pairs.append((old.path.name, new.path.name))
    if old.destination != new.destination:
        pairs.append((old.destination, new.destination))
    return sorted((pair for pair in pairs if pair[0] and pair[0] != pair[1]), key=lambda pair: -len(pair[0]))


def _replace_report(old: model_cfg.ModelDownload, new: model_cfg.ModelDownload) -> list[str]:
    """Print what changes and return Strata references that block an apply."""
    refs, _ = references(old)
    found_mentions = mentions(old)
    strata = [f"{ref.source}: {ref.path}" for ref in refs if ref.source.startswith("Strata:")]
    strata += [
        f"{display_path(item.path)}:{item.line}: {item.text}" for item in found_mentions if "strata" in item.path.parts
    ]
    print("\nOld references:")
    for ref in refs:
        print(f"  {ref.source}: {ref.path}")
    print("\nSubstitutions:")
    for source, target in replacement_pairs(old, new):
        print(f"  {source} -> {target}")
    if strata:
        print("\n[FAIL] Strata native config still references the old paths:")
        for line in strata:
            print(f"  {line}")
    return strata


def _replacement_changes(
    old: model_cfg.ModelDownload, new: model_cfg.ModelDownload, include_docs: bool, include_tests: bool
) -> list[tuple[Path, str]]:
    pairs = replacement_pairs(old, new)
    changed: list[tuple[Path, str]] = []
    for file in rewrite_files(include_docs, include_tests):
        text = file.read_text(encoding="utf-8-sig", errors="replace")
        updated = text
        for source, target in pairs:
            updated = updated.replace(source, target)
        if updated != text:
            changed.append((file, updated))
    return changed


def _print_changes(changed: list[tuple[Path, str]]) -> None:
    print("\nFiles to update:")
    for file, _ in changed:
        print(f"  {display_path(file)}")
    if not changed:
        print("  (none)")


def _print_dry_run(include_docs: bool, include_tests: bool) -> None:
    print("\n[Dry run] Re-run with --apply to rewrite files, edit catalog.json and move old weights to trash.")
    if not include_docs:
        print("Add --include-docs to update maintained Markdown documentation.")
    if not include_tests:
        print("Add --include-tests to update maintained test fixtures/assertions.")


def _retire_old(old: model_cfg.ModelDownload, new: model_cfg.ModelDownload, stamp: str) -> None:
    old_files = installed_files(old)
    if old_files:
        for file in old_files:
            move_to_trash(file, stamp)
    else:
        print(f"[WARN] No installed file for {old.label}; references were changed only.")
    if not new.path.is_file():
        print(f"[WARN] {new.label} is not installed; references now point at a missing file.")


def _apply_replacement(
    old: model_cfg.ModelDownload, new: model_cfg.ModelDownload, changed: list[tuple[Path, str]], stamp: str
) -> None:
    backup_file(catalog.entry_home(old.label), stamp)
    for file, updated in changed:
        backup_file(file, stamp)
        file.write_text(updated, encoding="utf-8")
        print(f"[OK] {display_path(file)}")
    catalog.remove_entry(old.label)
    catalog.write_ids()
    _retire_old(old, new, stamp)


def command_replace(
    old: model_cfg.ModelDownload,
    new: model_cfg.ModelDownload,
    apply: bool,
    include_docs: bool,
    include_tests: bool = False,
    download: bool = False,
) -> int:
    print(f"Replace {old.label} -> {new.label}")
    strata = _replace_report(old, new)
    if strata and apply:
        print("Update the native Strata model/mmproj paths manually first; nothing was changed.")
        return 1
    changed = _replacement_changes(old, new, include_docs, include_tests)
    _print_changes(changed)
    if not apply:
        if download and not new.path.is_file():
            print(f"\n--apply would download {new.label} before rewriting references.")
        _print_dry_run(include_docs, include_tests)
        return 0
    if strata:
        return 1
    if download and not new.path.is_file():
        from scripts.download.models import download_catalog

        download_catalog.download_model(new)
    stamp = str(time.time_ns())
    _apply_replacement(old, new, changed, stamp)
    print(f"[OK] Removed {old.label}; kept {new.label}")
    return run_model_sync()


def command_add(args: argparse.Namespace) -> int:
    entry = {
        "category": args.category,
        "group": args.group,
        "label": args.label,
        "filename": args.filename,
        "url": args.url,
        "in_use": args.in_use,
        "notes": args.notes,
        "sha256": args.sha256,
        "roles": list(args.roles or []),
        "runtimes": list(args.runtimes or []),
        "source_page": args.source_page,
    }
    target = catalog.overlay_path() if args.overlay else catalog.CATALOG_PATH
    if not target.is_file():
        print(f"[FAIL] Catalog file does not exist: {target}")
        return 1
    entries = [*catalog.load_entries(target), entry]
    try:
        catalog.validate_entries(entries)
    except ValueError as error:
        print(f"[FAIL] {error}")
        return 1
    print(json.dumps(entry, indent=2))
    if not args.apply:
        print(f"\n[Dry run] Re-run with --apply to append this entry to {display_path(target)}.")
        return 0
    stamp = str(time.time_ns())
    backup_file(target, stamp)
    catalog.upsert_entry(entry, target)
    if target == catalog.CATALOG_PATH:
        catalog.write_ids()
    print(f"[OK] Added {args.label} to {display_path(target)}")
    if args.download:
        from scripts.download.models import download_catalog as download

        download.download_model(catalog.get(args.label))
    return run_model_sync()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="Show one catalog entry and its references")
    status.add_argument("label")
    where = sub.add_parser("where", help="List every reference and source mention")
    where.add_argument("label")
    remove = sub.add_parser("remove", help="Dry-run or remove an unreferenced model")
    remove.add_argument("label")
    remove.add_argument("--apply", action="store_true", help="Edit catalog.json and move files to trash")
    replace = sub.add_parser("replace", help="Rewrite references and retire the old model")
    replace.add_argument("old")
    replace.add_argument("new")
    replace.add_argument("--apply", action="store_true", help="Rewrite files, edit catalog.json and move weights")
    replace.add_argument("--include-docs", action="store_true", help="Also rewrite maintained Markdown docs")
    replace.add_argument("--include-tests", action="store_true", help="Also rewrite maintained test fixtures")
    replace.add_argument("--download", action="store_true", help="Fetch the new model first when it is missing")
    add = sub.add_parser("add", help="Append a catalog entry")
    add.add_argument("--category", required=True, choices=catalog.CATEGORIES)
    add.add_argument("--group", required=True)
    add.add_argument("--label", required=True)
    add.add_argument("--filename", required=True)
    add.add_argument("--url")
    add.add_argument("--in-use", action="store_true")
    add.add_argument("--notes", default="")
    add.add_argument("--sha256")
    add.add_argument("--roles", nargs="+")
    add.add_argument("--runtimes", nargs="+")
    add.add_argument("--source-page")
    add.add_argument("--apply", action="store_true")
    add.add_argument("--overlay", action="store_true", help="Append to the input overlay instead of the catalog")
    add.add_argument("--download", action="store_true", help="Download after adding")
    args = parser.parse_args(argv)
    if args.command in ("status", "where"):
        model = model_for(args.label)
        return command_status(model)
    if args.command == "remove":
        return command_remove(model_for(args.label), args.apply)
    if args.command == "replace":
        old, new = model_for(args.old), model_for(args.new)
        if old.label == new.label:
            parser.error("old and new are the same catalog entry")
        return command_replace(old, new, args.apply, args.include_docs, args.include_tests, args.download)
    return command_add(args)


if __name__ == "__main__":
    raise SystemExit(main())
