"""Fetch newer releases of catalog models and swap them in.

`download_models` only fills gaps; this checks versioned families on the Hub, downloads the newer
file, rewrites references and retires the old weights. Catalog writes go to the file that owns the
old label, so private entries stay in the input overlay. `--dry-run` shows the swaps without changes.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.config.models import MODELS, ModelDownload, catalog
from scripts.download.models import download_catalog, updates
from scripts.download.models.hub_sources import parse_url
from scripts.tools import model_admin


@dataclass
class Candidate:
    old: ModelDownload
    entry: dict[str, Any]

    @property
    def label(self) -> str:
        return str(self.entry["label"])


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


def candidates(api: Any, models: list[ModelDownload]) -> list[Candidate]:
    """Newer releases whose file can be named unambiguously."""
    found: list[Candidate] = []
    for model in models:
        if not model.url:
            continue
        repo = parse_url(model.url).repo_id
        release = updates.latest_release(api, repo)
        if release is None:
            continue
        newer_repo, _ = release
        filename = _file_for(api, model, newer_repo)
        if filename is None:
            print(f"[WARN] {model.label}: {newer_repo} has no matching file; skipped", flush=True)
            continue
        found.append(Candidate(model, _entry(model, filename, newer_repo)))
    return found


def _apply(candidate: Candidate) -> bool:
    old = candidate.old
    refs, _ = model_admin.references(old)
    if any(ref.source.startswith("Strata:") for ref in refs):
        print(f"[SKIP] {old.label}: a Strata config references the old path", flush=True)
        return True
    catalog.upsert_entry(candidate.entry, catalog.entry_home(old.label))
    try:
        new = catalog.get(candidate.label)
        download_catalog.download_model(new)
    except Exception as error:  # - a failed download must leave the old entry in place
        catalog.remove_entry(candidate.label)
        print(f"[FAIL] {old.label} -> {candidate.label}: {error}", flush=True)
        return False
    code = model_admin.command_replace(old, new, apply=True, include_docs=False)
    return code == 0


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="update only these catalog labels")
    parser.add_argument("--dry-run", action="store_true", help="Show the swaps without downloading or replacing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    from huggingface_hub import HfApi

    api = HfApi(token=project_cfg.HF_TOKEN)
    models = [model for model in MODELS if model.in_use and model.url]
    if args.only:
        models = [model for model in models if model.label in set(args.only)]
    found = candidates(api, models)
    if not found:
        print("[OK] No newer releases for any versioned catalog family.")
        return 0
    print(f"{len(found)} newer release(s):")
    for candidate in found:
        print(f"  {candidate.old.label} -> {candidate.label}")
    if args.dry_run:
        print("\n[Dry run] Re-run without --dry-run to download, replace references and retire the old weights.")
        return 0
    failed = 0
    for index, candidate in enumerate(found, 1):
        print(f"\n[{index}/{len(found)}] {candidate.old.label} -> {candidate.label}", flush=True)
        if not _apply(candidate):
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
