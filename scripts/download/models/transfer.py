"""One place for model file transfers: the Hub client, staged per model.

Every attempt uses a freshly recreated `.hub-<model>` staging folder, so a lock left behind by a
crashed run cannot block the next transfer. The staged file is checked against the expected size and
only then moved into place.
"""

import shutil
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.config.models import ModelDownload
from scripts.download.models.hub_sources import parse_url


def staging_dir(model: ModelDownload) -> Path:
    return model.path.parent / f".hub-{model.path.stem}"


def fetch(model: ModelDownload, expected: int | None = None) -> Path:
    """Download into a clean staging folder and return the staged file."""
    from huggingface_hub import hf_hub_download

    source = parse_url(str(model.url))
    staging = staging_dir(model)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=source.repo_id,
            filename=source.filename,
            revision=source.revision,
            token=project_cfg.HF_TOKEN,
            local_dir=str(staging),
        )
    )
    if expected and downloaded.stat().st_size != expected:
        raise RuntimeError(f"downloaded {downloaded.stat().st_size} bytes, expected {expected}")
    return downloaded


def commit(part: Path, destination: Path) -> None:
    part.replace(destination)
    if part.parent.name.startswith(".hub-"):
        shutil.rmtree(part.parent, ignore_errors=True)


def download(model: ModelDownload, expected: int | None = None) -> Path:
    """Fetch a complete file and move it to its catalog path."""
    commit(fetch(model, expected), model.path)
    return model.path
