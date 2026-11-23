"""One place for model file transfers: the Hub client, staged per model.

Every attempt uses a freshly recreated `.hub-<model>` staging folder, so a lock left behind by a
crashed run cannot block the next transfer. The staged file is checked against the expected size and
only then moved into place.
"""

import hashlib
import shutil
from pathlib import Path

import huggingface_hub

from scripts.config import project_config as project_cfg
from scripts.config.models import ModelDownload
from scripts.download.models.hub_sources import parse_url


def staging_dir(model: ModelDownload) -> Path:
    return model.path.parent / f".hub-{model.path.stem}"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, model: ModelDownload, expected: int | None = None) -> None:
    """A staged file must match its size and its recorded digest before it can replace anything.

    The catalog's `sha256` is the only proof that a transfer completed as published; the Hub client does
    not check it for us, so a truncated or corrupted download would otherwise be moved into place as if
    complete. An entry without a recorded digest keeps the size check alone.
    """
    size = path.stat().st_size
    if expected and size != expected:
        raise RuntimeError(f"downloaded {size} bytes, expected {expected}")
    recorded = (model.sha256 or "").lower()
    if not recorded:
        return
    actual = file_digest(path)
    if actual != recorded:
        raise RuntimeError(f"SHA-256 mismatch for {path}: expected {recorded}, got {actual}; file not moved")


def fetch(model: ModelDownload, expected: int | None = None) -> Path:
    """Download into a clean staging folder and return the staged, verified file."""
    source = parse_url(str(model.url))
    staging = staging_dir(model)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        huggingface_hub.hf_hub_download(
            repo_id=source.repo_id,
            filename=source.filename,
            revision=source.revision,
            token=project_cfg.HF_TOKEN,
            local_dir=str(staging),
        )
    )
    verify(downloaded, model, expected)
    return downloaded


def commit(part: Path, destination: Path) -> None:
    part.replace(destination)
    if part.parent.name.startswith(".hub-"):
        shutil.rmtree(part.parent, ignore_errors=True)


def download(model: ModelDownload, expected: int | None = None) -> Path:
    """Fetch a complete file and move it to its catalog path."""
    commit(fetch(model, expected), model.path)
    return model.path
