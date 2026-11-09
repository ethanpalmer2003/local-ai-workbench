"""One place for model file transfers, with two modes.

`download_stream` uses plain authenticated HTTP ranges into a resumable `.part` file; it works when
the Xet backend stalls and resumes a partial transfer. `download_hub` uses the Hub client, which can
deduplicate chunks through Xet but stalls on large files here.
"""

from pathlib import Path

import requests
from tqdm import tqdm

from scripts.config import project_config as project_cfg
from scripts.config.models import ModelDownload
from scripts.download.models.hub_sources import parse_url

CHUNK = 1024 * 1024
MODES = ("stream", "hub")


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


def commit(part: Path, destination: Path) -> None:
    part.replace(destination)


def download_stream(model: ModelDownload, expected: int | None = None, limit: int | None = None) -> Path:
    """Stream a complete file into place; a failed transfer leaves the `.part` for a rerun."""
    part = stream_part(model, expected, limit)
    if limit is None:
        commit(part, model.path)
    return part


def download_hub(model: ModelDownload) -> Path:
    """The Hub client path: cache aware and Xet-capable, with the same final destination."""
    from huggingface_hub import hf_hub_download

    model.path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=parse_url(str(model.url)).repo_id,
            filename=parse_url(str(model.url)).filename,
            revision=parse_url(str(model.url)).revision,
            token=project_cfg.HF_TOKEN,
            local_dir=str(model.path.parent),
        )
    )
    if downloaded != model.path:
        downloaded.replace(model.path)
    return model.path
