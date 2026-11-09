"""Bring catalog models up to date: newer releases are swapped in, drifted files are refreshed.

`download_models` only fills gaps; this checks every active source, upgrades versioned families whose
newer file can be named unambiguously, and refreshes files whose size no longer matches the Hub. A
refresh is still a model download: the version and file name did not change, so the pinned file is
fetched again. Both paths use `scripts.download.models.transfer`, so an interrupted transfer resumes.
Upgrades write to the catalog file that owns the old label, so private entries stay in the overlay.
`--dry-run` shows the plan without downloading or replacing anything.
"""

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

from scripts.config import project_config as project_cfg
from scripts.config.models import MODELS, ModelDownload, catalog
from scripts.download.models import transfer, updates
from scripts.download.models.hub_sources import parse_url
from scripts.tools import model_admin


@dataclass
class Action:
    kind: str
    model: ModelDownload
    entry: dict[str, Any] | None = None
    expected: int | None = None

    @property
    def label(self) -> str:
        return str(self.entry["label"]) if self.entry else self.model.label


def _file_for(api: Any, old: ModelDownload, repo: str) -> str | None:
    """The newer repo's file: the old name with the new version, or a unique same-quant match."""
    name = Path(old.filename or old.path.name).name
    version = updates.RELEASE.search(repo.rsplit("/", 1)[-1])
    match = updates.FILE_VERSION.search(name)
    if version is None or match is None:
        return None
    try:
        files = list(api.list_repo_files(repo))
    except Exception:  # - an unreachable repo is reported as no candidate
        return None
    swapped = f"{name[: match.start()]}-v{version.group('version')}{name[match.end() :]}"
    if swapped in files:
        return swapped
    matches = [item for item in files if item.endswith(name[match.end() :]) and "/" not in item]
    return matches[0] if len(matches) == 1 else None


def _entry(old: ModelDownload, filename: str, repo: str) -> dict[str, Any]:
    base = Path(filename).name
    return {
        "category": old.category,
        "group": old.group,
        "label": f"{old.group}/{Path(base).stem}",
        "filename": base,
        "url": f"https://huggingface.co/{repo}/blob/main/{filename}",
        "in_use": True,
        "notes": old.notes,
        "sha256": None,
        "roles": list(old.roles),
        "runtimes": list(old.runtimes),
        "source_page": old.source_page,
    }


def _upgrade(api: Any, model: ModelDownload) -> Action | None:
    release = updates.latest_release(api, parse_url(model.url).repo_id) if model.url else None
    if release is None:
        return None
    newer_repo, _ = release
    filename = _file_for(api, model, newer_repo)
    if filename is None:
        tqdm.write(f"[WARN] {model.label}: {newer_repo} has no matching file; skipped")
        return None
    return Action("upgrade", model, _entry(model, filename, newer_repo))


def plan(api: Any, models: list[ModelDownload]) -> list[Action]:
    """Upgrades for versioned families with a newer release, and refreshes for size drift."""
    actions: list[Action] = []
    for model in models:
        if not model.url:
            continue
        row = updates.check(model, api)
        if row.newer:
            upgrade = _upgrade(api, model)
            if upgrade is not None:
                actions.append(upgrade)
            continue
        if row.source == "changed":
            actions.append(Action("refresh", model, expected=row.upstream_bytes))
        elif row.source in {"missing", "unreachable"}:
            tqdm.write(f"[WARN] {model.label}: source is {row.source}; skipped")
    return actions


def _apply_upgrade(action: Action) -> bool:
    old = action.model
    entry = action.entry
    if entry is None:
        tqdm.write(f"[FAIL] {old.label}: upgrade action has no catalog entry")
        return False
    refs, _ = model_admin.references(old)
    if any(ref.source.startswith("Strata:") for ref in refs):
        tqdm.write(f"[SKIP] {old.label}: a Strata config references the old path")
        return True
    catalog.upsert_entry(entry, catalog.entry_home(old.label))
    new = catalog.get(action.label)
    try:
        transfer.download(new)
    except Exception as error:  # - a failed download must leave the old entry in place
        catalog.remove_entry(action.label)
        tqdm.write(f"[FAIL] {old.label} -> {action.label}: {error}")
        return False
    return model_admin.command_replace(old, new, apply=True, include_docs=False) == 0


def _apply_refresh(action: Action) -> bool:
    model = action.model
    if not model.url or not model.url.startswith("https://huggingface.co/"):
        tqdm.write(f"[SKIP] {model.label}: refresh is only implemented for Hub files")
        return True
    try:
        part = transfer.fetch(model, action.expected)
        size = part.stat().st_size
        if model.path.is_file():
            model_admin.move_to_trash(model.path, str(time.time_ns()))
        transfer.commit(part, model.path)
        tqdm.write(f"[OK] Refreshed {model.label} ({size} bytes)")
        return True
    except Exception as error:
        tqdm.write(f"[FAIL] {model.label}: {error}")
        return False


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="update only these catalog labels")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without downloading or replacing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    from huggingface_hub import HfApi

    api = HfApi(token=project_cfg.HF_TOKEN)
    models = [model for model in MODELS if model.in_use and model.url]
    if args.only:
        models = [model for model in models if model.label in set(args.only)]
    actions = plan(api, models)
    if not actions:
        print("[OK] Nothing to update: no newer releases and no size drift.")
        return 0
    print(f"{len(actions)} action(s):")
    for action in actions:
        print(f"  {action.kind:<8} {action.model.label}" + (f" -> {action.label}" if action.entry else ""))
    if args.dry_run:
        print("\n[Dry run] Re-run without --dry-run to download, replace references and retire the old weights.")
        return 0
    failed = 0
    with tqdm(total=len(actions), desc="models", ascii=True, unit="action") as bar:
        for action in actions:
            bar.set_postfix_str(action.kind)
            ok = _apply_upgrade(action) if action.kind == "upgrade" else _apply_refresh(action)
            bar.update(1)
            if not ok:
                failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
