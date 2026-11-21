"""Provision the portable MeCab DLL from the newest Windows wheel; no pip install."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import requests

from scripts.config import project_config as project_cfg

PACKAGE = "mecab-python3"
PYPI = "https://pypi.org/pypi/{package}/json"
WHEEL_SUFFIX = "-win_amd64.whl"
# - the wheel is unpacked for one DLL, so the largest archive this reads stays bounded
ARCHIVE_LIMIT = 16 * 1024 * 1024


def latest_wheel(package: str) -> tuple[str, str]:
    """The current version and the Windows wheel that carries its native library."""
    response = requests.get(PYPI.format(package=package), timeout=30)
    response.raise_for_status()
    data = response.json()
    version = str(data["info"]["version"])
    wheels = [item for item in data["urls"] if str(item["filename"]).endswith(WHEEL_SUFFIX)]
    if not wheels:
        raise ValueError(f"{package} {version} publishes no Windows wheel")
    return version, str(wheels[0]["url"])


def installed_version(root: Path) -> str | None:
    """The version recorded beside the extracted DLL; the field has carried both forms."""
    record = root / "INSTALL.json"
    if not record.is_file():
        return None
    tokens = str(json.loads(record.read_text(encoding="utf-8")).get("version", "")).split()
    return tokens[-1] if tokens else None


def install(wheel_url: str, root: Path, version: str) -> None:
    response = requests.get(wheel_url, timeout=60)
    response.raise_for_status()
    data = response.content[:ARCHIVE_LIMIT]
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if name.endswith("/libmecab.dll") or "/licenses/" in name:
                (root / name.rsplit("/", 1)[-1]).write_bytes(archive.read(name))
    if not (root / "libmecab.dll").is_file():
        raise RuntimeError("Wheel did not contain the expected MeCab DLL")
    (root / "INSTALL.json").write_text(
        json.dumps(
            {
                "version": version,
                "source": wheel_url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "scope": "Portable MeCab native DLL/licenses only; Python package not installed",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Portable MeCab {version} -> {root}")


def main() -> None:
    root = project_cfg.component("audiocpp/additions/mecab").framework_dir
    version, wheel = latest_wheel(PACKAGE)
    install(wheel, root, version)


if __name__ == "__main__":
    main()
