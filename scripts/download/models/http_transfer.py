"""Checksum-required HTTPS downloads for curated non-Hub model assets."""

import hashlib
import re
import tempfile
from pathlib import Path


def download_verified(url: str, destination: Path, checksum: str | None) -> None:
    import requests

    if not url.startswith("https://") or not re.fullmatch(r"[a-f0-9]{64}", checksum or ""):
        raise ValueError("Non-Hub assets require an HTTPS source and a pinned SHA256")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        if not response.url.startswith("https://"):
            raise ValueError("Refusing an insecure download redirect")
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=destination.name + ".", suffix=".part", delete=False
        ) as partial:
            for chunk in response.iter_content(chunk_size=1 << 20):
                partial.write(chunk)
                digest.update(chunk)
    staged = Path(partial.name)
    if digest.hexdigest() != checksum:
        raise ValueError(f"SHA256 mismatch; partial download preserved: {staged}")
    if destination.exists():
        raise FileExistsError(f"Destination appeared during download; verified partial preserved: {staged}")
    staged.rename(destination)
    print(f"[OK] SHA256 verified: {destination}")
