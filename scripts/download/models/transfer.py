"""One place for model file transfers, with two modes.

`download_hub` (default) uses the Hub client: cache aware and Xet capable, which is fastest here and
reuses chunks. `download_stream` uses plain authenticated HTTP ranges into a resumable `.part`; it is
the fallback when the Hub client stalls, and it can stop after a byte limit for a connectivity check.
"""

import shutil
from pathlib import Path

import requests
from tqdm import tqdm

from scripts.config import project_config as project_cfg
from scripts.config.models import ModelDownload
from scripts.download.models.hub_sources import parse_url

CHUNK = 1024 * 1024
DEFAULT_MODE = "hub"
MODES = ("hub", "stream")


def resolve_url(model: ModelDownload) -> str:
    source = parse_url(str(model.url))
    return f"https://huggingface.co/{source.repo_id}/resolve/{source.revision}/{source.filename}"


def part_path(model: ModelDownload) -> Path:
    return model.path.with_name(model.path.name + ".part")


def stream_part(model: ModelDownload, expected: int | None = None, limit: int | None = None) -> Path:
    """Fetch into the sibling `.part` file, resuming it, and return that path.

    `limit` stops after that many bytes and keeps the partial; it is a connectivity check.
    """
    destination = part_path(model)
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {project_cfg.HF_TOKEN}"} if project_cfg.HF_TOKEN else {}
    offset = destination.stat().st_size if destination.is_file() else 0
    if expected and offset > expected:
        destination.unlink()
        offset = 0
    if offset:
        headers["Range"] = f"bytes={offset}-"
    with requests.get(
        resolve_url(model), headers=headers, stream=True, timeout=(30, 300), allow_redirects=True
    ) as response:
        if response.status_code not in (200, 206):
            raise RuntimeError(f"HTTP {response.status_code} for {model.label}")
        mode = "ab" if offset and response.status_code == 206 else "wb"
        if mode == "wb":
            offset = 0
        total = expected or offset + int(response.headers.get("Content-Length") or 0)
        with (
            destination.open(mode) as handle,
            tqdm(
                total=total,
                initial=offset,
                unit="B",
                unit_scale=True,
                desc=model.label,
                ascii=True,
                position=1,
                leave=False,
            ) as bar,
        ):
            for chunk in response.iter_content(chunk_size=CHUNK):
                if not chunk:
                    continue
                handle.write(chunk)
                bar.update(len(chunk))
                if limit is not None and bar.n >= limit:
                    break
    if expected and limit is None and destination.stat().st_size != expected:
        raise RuntimeError(f"downloaded {destination.stat().st_size} bytes, expected {expected}")
    return destination


def hub_part(model: ModelDownload, expected: int | None = None) -> Path:
    """Download through the Hub client into a clean staging folder and return that file.

    The staging folder is recreated first: a crashed run can leave a lock file behind, and the next
    attempt would then wait on it instead of transferring.
    """
    from huggingface_hub import hf_hub_download

    staging = model.path.parent / f".hub-{model.path.stem}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=parse_url(str(model.url)).repo_id,
            filename=parse_url(str(model.url)).filename,
            revision=parse_url(str(model.url)).revision,
            token=project_cfg.HF_TOKEN,
            local_dir=str(staging),
        )
    )
    if expected and downloaded.stat().st_size != expected:
        raise RuntimeError(f"downloaded {downloaded.stat().st_size} bytes, expected {expected}")
    return downloaded


def fetch_part(
    model: ModelDownload, expected: int | None = None, limit: int | None = None, mode: str = DEFAULT_MODE
) -> Path:
    """Fetch this model's file with the requested mode and return the completed path.

    A byte limit is only meaningful for the streaming mode, so it selects that mode.
    """
    if limit is not None:
        mode = "stream"
    if mode == "hub":
        return hub_part(model, expected)
    return stream_part(model, expected, limit)


def commit(part: Path, destination: Path) -> None:
    part.replace(destination)
    if part.parent.name.startswith(".hub-"):
        shutil.rmtree(part.parent, ignore_errors=True)


def download(model: ModelDownload, expected: int | None = None, mode: str = DEFAULT_MODE) -> Path:
    """Fetch a complete file into its final path; a failed stream leaves the `.part` for a rerun."""
    part = fetch_part(model, expected, None, mode)
    commit(part, model.path)
    return model.path


def download_stream(model: ModelDownload, expected: int | None = None, limit: int | None = None) -> Path:
    part = stream_part(model, expected, limit)
    if limit is None:
        commit(part, model.path)
    return part


def download_hub(model: ModelDownload, expected: int | None = None) -> Path:
    part = hub_part(model, expected)
    commit(part, model.path)
    return model.path
