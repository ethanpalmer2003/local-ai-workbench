"""The pinned multilingual corpus a language run speaks and hears.

The audio itself is downloaded (`scripts.download.benchmarks.fleurs`); this module turns the
tracked manifest plus the downloaded clips into run artifacts and the provenance a long run
records, so a changed corpus revision is visible instead of silently mixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.paths import RunPaths
from scripts.download.benchmarks import fleurs


def manifest() -> dict[str, Any]:
    return fleurs.spec()


def identity() -> dict[str, Any]:
    """Corpus identity a report records: revision, manifest hash and clip count."""
    value = fleurs.spec()
    return {
        "corpus": value["corpus"],
        "corpus_name": value.get("corpus_name", ""),
        "revision": value["revision"],
        "split": value["split"],
        "manifest": str(fleurs.manifest_path()),
        "manifest_sha256": fleurs.manifest_sha256(),
        "clips": len(value["clips"]),
    }


def missing() -> list[Path]:
    return fleurs.missing()


def root() -> Path:
    """Folder holding this corpus revision's extracted audio."""
    return fleurs.corpus_root()


def prepare(run: RunPaths) -> list[dict[str, Any]]:
    """Copy this run's clips to 16 kHz mono artifacts and return the prepared rows."""
    from scripts.tests.cases.asr.shared.corpus import prepare_corpus

    outstanding = missing()
    if outstanding:
        raise FileNotFoundError(
            f"{len(outstanding)} corpus clips are not downloaded; run "
            f"python -m scripts.download.benchmarks.fleurs --download"
        )
    root = fleurs.corpus_root()
    rows = [
        {
            "id": clip["id"],
            "file": str(fleurs.clip_path(clip, root)),
            "reference": clip["reference"],
            "language": clip["language"],
        }
        for clip in fleurs.spec()["clips"]
    ]
    staged = run.temp / "corpus-manifest.json"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return prepare_corpus(run, staged)
