"""Authenticated, checksum-verified range fallback for catalog downloads."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from scripts.config import project_config as project_cfg
from scripts.download.models.hub_sources import HubFile


class _RangeFetcher:
    """One authenticated request per contiguous chunk."""

    chunk_size = 32 * 1024**2

    def __init__(self, url: str, headers: dict[str, str], metadata: Any) -> None:
        self.url = url
        self.headers = headers
        self.metadata = metadata

    def fetch(self, start: int) -> bytes:
        from huggingface_hub.utils import get_session

        end = min(self.metadata.size, start + self.chunk_size) - 1
        # Requests strips Authorization on cross-host redirects to signed storage URLs.
        response = get_session().get(
            self.url, headers={**self.headers, "Range": f"bytes={start}-{end}"}, timeout=cast(Any, (15, 60))
        )
        try:
            response.raise_for_status()
            expected = f"bytes {start}-{end}/{self.metadata.size}"
            if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                raise ValueError("Unexpected range response; partial file preserved")
            data = response.content
            if len(data) != end - start + 1:
                raise ValueError("Incomplete range; partial file preserved")
            return data
        finally:
            response.close()


def _partial_target(destination: Path, partial: Path | None, size: int) -> tuple[Path, int]:
    if destination.exists():
        raise FileExistsError(f"Destination already exists; preserved: {destination}")
    resolved = partial or destination.with_suffix(destination.suffix + ".part")
    if resolved.resolve() == destination.resolve():
        raise ValueError("Partial and final destinations must differ")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    offset = resolved.stat().st_size if resolved.exists() else 0
    if offset > size:
        raise ValueError("Partial file exceeds expected size; preserved")
    return resolved, offset


def _verify_and_move(partial: Path, destination: Path, etag: str) -> None:
    with partial.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != etag:
        raise ValueError("SHA-256 mismatch; partial file preserved")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial.rename(destination)
    print(f"[OK] SHA-256 verified: {destination}")


def download_ranges(source: HubFile, destination: Path, partial: Path | None = None) -> None:
    from huggingface_hub import get_hf_file_metadata, hf_hub_url
    from huggingface_hub.utils import build_hf_headers

    token = project_cfg.HF_TOKEN or False
    url = hf_hub_url(source.repo_id, source.filename, revision=source.revision)
    metadata = get_hf_file_metadata(url, token=token)
    if metadata.size is None or metadata.etag is None or len(metadata.etag) != 64:
        raise ValueError("Range fallback requires a file size and SHA-256 Hub ETag")
    partial, offset = _partial_target(destination, partial, metadata.size)
    fetcher = _RangeFetcher(url, build_hf_headers(token=token), metadata)
    with partial.open("ab") as out, ThreadPoolExecutor(max_workers=4) as pool:
        while offset < metadata.size:
            starts = range(offset, min(metadata.size, offset + 4 * fetcher.chunk_size), fetcher.chunk_size)
            for data in pool.map(fetcher.fetch, starts):
                out.write(data)
                out.flush()
                offset += len(data)
            print(f"[DOWNLOAD] {offset}/{metadata.size} bytes ({offset / metadata.size:.1%})", flush=True)
    _verify_and_move(partial, destination, metadata.etag)
