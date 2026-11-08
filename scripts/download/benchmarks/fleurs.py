"""Download the pinned corpus clips that the language comparison speaks and hears.

The tracked manifest (`scripts/config/benchmarks/language_corpus.json`) records the corpus
revision, the split, each selected clip member and its reference text; this module fetches the
pinned archives and extracts only those clips, so a run never depends on a moving corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg

MANIFEST_NAME = "download.json"


def manifest_path() -> Path:
    return project_cfg.component("benchmarks").config_dir / "language_corpus.json"


def spec() -> dict[str, Any]:
    """The committed corpus manifest."""
    value = json.loads(manifest_path().read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value.get("corpus") or not value.get("clips"):
        raise ValueError(f"Corpus manifest needs a corpus name and clips: {manifest_path()}")
    return value


def manifest_sha256() -> str:
    return hashlib.sha256(manifest_path().read_bytes()).hexdigest()


def corpus_root(manifest: dict[str, Any] | None = None) -> Path:
    """Where this corpus revision's audio lives; the revision keeps old runs reproducible."""
    value = manifest or spec()
    name = str(value.get("corpus_name") or value["corpus"]).lower()
    return project_cfg.component("benchmarks").models_dir / "corpora" / name / str(value["revision"])


def clip_path(clip: dict[str, Any], root: Path | None = None) -> Path:
    return (root or corpus_root()) / str(clip["config"]) / Path(str(clip["member"])).name


def missing(manifest: dict[str, Any] | None = None) -> list[Path]:
    value = manifest or spec()
    root = corpus_root(value)
    return [clip_path(clip, root) for clip in value["clips"] if not clip_path(clip, root).is_file()]


def _archive(manifest: dict[str, Any], config: str) -> Path:
    from huggingface_hub import hf_hub_download

    split = str(manifest["split"])
    return Path(
        hf_hub_download(
            repo_id=str(manifest["corpus"]),
            filename=f"data/{config}/audio/{split}.tar.gz",
            repo_type="dataset",
            revision=str(manifest["revision"]),
            token=project_cfg.HF_TOKEN,
        )
    )


def _extract(archive: Path, wanted: dict[str, Path]) -> None:
    """Stream the archive once and write only the members this run needs."""
    pending = dict(wanted)
    with tarfile.open(archive, mode="r|gz") as tar:
        for member in tar:
            target = pending.pop(member.name, None)
            if target is None:
                continue
            source = tar.extractfile(member)
            if source is None:
                raise ValueError(f"Archive member is not a regular file: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            if not pending:
                return
    if pending:
        raise ValueError(f"Archive {archive.name} is missing {sorted(pending)}")


def _lfs_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    """Upstream SHA-256 for each archive, straight from the pinned dataset revision."""
    from huggingface_hub import HfApi

    info = HfApi(token=project_cfg.HF_TOKEN).dataset_info(
        str(manifest["corpus"]), revision=str(manifest["revision"]), files_metadata=True
    )
    return {
        sibling.rfilename: str(sibling.lfs.sha256)
        for sibling in info.siblings or ()
        if sibling.lfs is not None and sibling.rfilename.endswith(".tar.gz")
    }


def _clip_rows(manifest: dict[str, Any], config: str, root: Path) -> list[dict[str, Any]]:
    rows = []
    for clip in manifest["clips"]:
        if clip["config"] != config:
            continue
        path = clip_path(clip, root)
        rows.append(
            {
                "id": clip["id"],
                "file": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return rows


def _configs(manifest: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(str(clip["config"]) for clip in manifest["clips"]))


def download(force: bool = False) -> dict[str, Any]:
    """Fetch every archive a manifest clip belongs to, then extract those clips."""
    manifest = spec()
    root = corpus_root(manifest)
    archives = _lfs_hashes(manifest)
    recorded: dict[str, Any] = {
        "corpus": manifest["corpus"],
        "revision": manifest["revision"],
        "split": manifest["split"],
        "manifest": str(manifest_path().relative_to(project_cfg.BASE_DIR)),
        "manifest_sha256": manifest_sha256(),
        "archives": {},
        "clips": [],
    }
    for config in _configs(manifest):
        archive = _archive(manifest, config)
        wanted = {str(clip["member"]): clip_path(clip, root) for clip in manifest["clips"] if clip["config"] == config}
        outstanding = {name: path for name, path in wanted.items() if force or not path.is_file()}
        if outstanding:
            print(f"{config}: extracting {len(outstanding)} clip(s) from {archive.name}", flush=True)
            _extract(archive, outstanding)
        sibling = f"data/{config}/audio/{manifest['split']}.tar.gz"
        recorded["archives"][config] = {
            "file": archive.name,
            "cached": str(archive),
            "sha256": archives.get(sibling, ""),
        }
        recorded["clips"].extend(_clip_rows(manifest, config, root))
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_NAME).write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    return recorded


def state() -> dict[str, Any]:
    """What is on disk right now, without touching the network."""
    manifest = spec()
    root = corpus_root(manifest)
    recorded = root / MANIFEST_NAME
    return {
        "corpus": manifest["corpus"],
        "revision": manifest["revision"],
        "manifest_sha256": manifest_sha256(),
        "root": str(root),
        "clips": len(manifest["clips"]),
        "missing": [str(path) for path in missing(manifest)],
        "recorded": json.loads(recorded.read_text(encoding="utf-8")) if recorded.is_file() else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Fetch and extract the selected clips")
    parser.add_argument("--force", action="store_true", help="Re-extract clips that are already present")
    args = parser.parse_args(argv)
    if args.force and not args.download:
        parser.error("--force only applies to --download")
    if args.download:
        recorded = download(args.force)
        print(f"[OK] {len(recorded['clips'])} clips in {corpus_root()}")
        return 0
    current = state()
    present = current["clips"] - len(current["missing"])
    print(f"{current['corpus']} @ {current['revision']}")
    print(f"manifest {current['manifest_sha256']}")
    print(f"clips {present}/{current['clips']} present in {current['root']}")
    for path in current["missing"][:5]:
        print(f"[MISSING] {path}")
    if current["missing"]:
        print("[NEXT] python -m scripts.download.benchmarks.fleurs --download")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
