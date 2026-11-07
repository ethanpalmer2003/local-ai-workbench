"""Provision the portable MeCab DLL from a checksum-pinned Windows wheel; no pip install."""

import hashlib
import io
import json
import urllib.request
import zipfile

from scripts.config import project_config as project_cfg

URL = "https://files.pythonhosted.org/packages/e9/ff/6f63a75ea7983c10dd85d81df696efc1b4edf80731757ab1ccb19777325b/mecab_python3-1.0.12-cp313-cp313-win_amd64.whl"
SHA256 = "ad8508d0bf9827b6ad4b3537d144a1ecbbd6a6841b74430c6b74fe4b8766aa42"


def main():
    with urllib.request.urlopen(URL, timeout=30) as response:
        data = response.read(16 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("MeCab wheel checksum mismatch")
    root = project_cfg.component("audiocpp/additions/mecab").framework_dir
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if name.endswith("/libmecab.dll") or "/licenses/" in name:
                target = root / name.rsplit("/", 1)[-1]
                content = archive.read(name)
                if target.exists() and target.read_bytes() != content:
                    raise RuntimeError("Different installed MeCab file; preserve it before replacement")
                target.write_bytes(content)
    if not (root / "libmecab.dll").is_file():
        raise RuntimeError("Wheel did not contain the expected MeCab DLL")
    (root / "INSTALL.json").write_text(
        json.dumps(
            {
                "version": "mecab-python3 1.0.12",
                "source": URL,
                "sha256": SHA256,
                "scope": "Portable MeCab native DLL/licenses only; Python package not installed",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Portable MeCab -> {root}")


if __name__ == "__main__":
    main()
