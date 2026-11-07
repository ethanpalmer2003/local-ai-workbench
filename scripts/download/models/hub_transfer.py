"""Authenticated, checksum-verified range fallback for catalog downloads."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.models.hub_sources import HubFile


def download_ranges(source: HubFile, destination: Path, partial: Path | None = None) -> None:
    from huggingface_hub import get_hf_file_metadata, hf_hub_url
    from huggingface_hub.utils import build_hf_headers, get_session

    token = project_cfg.HF_TOKEN or False
    url = hf_hub_url(source.repo_id, source.filename, revision=source.revision)
    metadata = get_hf_file_metadata(url, token=token)
    if metadata.size is None or metadata.etag is None or len(metadata.etag) != 64:
        raise ValueError("Range fallback requires a file size and SHA-256 Hub ETag")
    size = metadata.size
    if destination.exists():
        raise FileExistsError(f"Destination already exists; preserved: {destination}")
    partial = partial or destination.with_suffix(destination.suffix + ".part")
    if partial.resolve() == destination.resolve():
        raise ValueError("Partial and final destinations must differ")
    partial.parent.mkdir(parents=True, exist_ok=True)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > metadata.size:
        raise ValueError("Partial file exceeds expected size; preserved")
    headers = build_hf_headers(token=token)
    chunk_size = 32 * 1024**2

    def fetch(start: int) -> bytes:
        end = min(size, start + chunk_size) - 1
        # Requests strips Authorization on cross-host redirects to signed storage URLs.
        with get_session().get(url, headers={**headers, "Range": f"bytes={start}-{end}"}, timeout=(15, 60)) as response:
            response.raise_for_status()
            if (
                response.status_code != 206
                or response.headers.get("Content-Range") != f"bytes {start}-{end}/{metadata.size}"
            ):
                raise ValueError("Unexpected range response; partial file preserved")
            data = response.content
            if len(data) != end - start + 1:
                raise ValueError("Incomplete range; partial file preserved")
            return data

    with partial.open("ab") as out, ThreadPoolExecutor(max_workers=4) as pool:
        while offset < metadata.size:
            starts = range(offset, min(metadata.size, offset + 4 * chunk_size), chunk_size)
            for data in pool.map(fetch, starts):
                out.write(data)
                out.flush()
                offset += len(data)
            print(f"[DOWNLOAD] {offset}/{metadata.size} bytes ({offset / metadata.size:.1%})", flush=True)
    with partial.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != metadata.etag:
        raise ValueError("SHA-256 mismatch; partial file preserved")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial.rename(destination)
    print(f"[OK] SHA-256 verified: {destination}")
