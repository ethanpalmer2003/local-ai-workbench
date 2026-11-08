"""TTS runtime releases and Piper wheel installation."""

import json
import shutil
import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import update_shared as shared
from scripts.download.frameworks.update_types import ReleaseType, ToolSpec


def install_wheel(asset: shared.Asset, destination: Path, temporary: Path, exe_name: str) -> None:
    """Install prebuilt Python runtime/dependencies under one framework, using uv."""
    uv = shutil.which("uv")
    if not uv:
        raise shared.UpdateError("uv is required for the isolated Piper framework install")
    wheel = shared.download_asset(asset, temporary)
    from importlib.metadata import distributions

    staged = shared.staging_directory(temporary, prefix="piper-")
    python = project_cfg.SCRIPTS_DIR / ".venv/Scripts/python.exe"
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--target",
            str(staged),
            "--only-binary",
            ":all:",
            "--no-progress",
            str(wheel),
        ],
        check=True,
        timeout=240,
    )
    required = (exe_name, "onnxruntime/__init__.py", "pathvalidate/__init__.py")
    if not all((staged / name).is_file() for name in required):
        raise shared.UpdateError("Piper package or runtime dependencies are missing from the staged installation")
    versions = {dist.metadata["Name"]: dist.version for dist in distributions(path=[str(staged)])}
    (staged / "INSTALL.json").write_text(
        json.dumps({"asset": asset, "dependencies": versions, "python": str(python)}, indent=2), encoding="utf-8"
    )
    shared.replace_installation(staged, destination)


TOOLS = [
    # - both stay installed as comparison alternatives; AudioCpp is the selected runtime,
    #   so nothing updates them until that changes
    ToolSpec(
        "tts/sherpa-onnx",
        "bin/sherpa-onnx-offline-tts.exe",
        ReleaseType.DATE,
        repo="k2-fsa/sherpa-onnx",
        asset_pattern=r"^sherpa-onnx-v.*-win-x64-shared-MD-Release\.tar\.bz2$",
        in_use=False,
    ),
    ToolSpec(
        "tts/piper",
        "piper/__main__.py",
        ReleaseType.WHEEL,
        repo="OHF-Voice/piper1-gpl",
        asset_pattern=r"^piper_tts-.*-cp(?:39|310|311|312|313)-abi3-win_amd64\.whl$",
        in_use=False,
    ),
]
