"""Loom SDK, server and device-tool releases from ROCm/hrx-system.

The release ships three things this repo uses: the `hrx-loom` wheel (the `loom` package plus `loom-fetch`,
`loom-serve` and the other console scripts), a self-contained `loom-serve` executable, and `amdf-info` for
device discovery. The instrumented wheels (`+tracy`, `+debug`, `+asan`) are separate assets and are not
selected here.
"""

import json
import shutil
import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import update_shared as shared
from scripts.download.frameworks.update_types import ReleaseType, ToolSpec

REPO = "ROCm/hrx-system"
# - the release-profile wheel: a `+tag` or `dev0` version would name another build profile
SDK_ASSET = r"^hrx_loom-\d[^-+]*-py3-none-win_amd64\.whl$"
SERVE_ASSET = r"^loom-serve-.*-win_amd64\.zip$"
INFO_ASSET = r"^amdf-info-.*-win_amd64\.zip$"

TOOLS = [
    ToolSpec("loom/sdk", "loom/__init__.py", ReleaseType.SDK, repo=REPO, asset_pattern=SDK_ASSET),
    ToolSpec("loom/serve", "loom-serve.exe", ReleaseType.DATE, repo=REPO, asset_pattern=SERVE_ASSET),
    ToolSpec("loom/tools", "amdf-info.exe", ReleaseType.DATE, repo=REPO, asset_pattern=INFO_ASSET),
]


def install_sdk(asset: shared.Asset, destination: Path, temporary: Path, exe_name: str) -> None:
    """Install the SDK wheel into its own folder, so the shared venv stays as it is."""
    uv = shutil.which("uv")
    if not uv:
        raise shared.UpdateError("uv is required to install the Loom SDK wheel")
    wheel = shared.download_asset(asset, temporary)
    staged = shared.staging_directory(temporary, prefix="loom-sdk-")
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(project_cfg.VENV_DIR / "Scripts" / "python.exe"),
            "--target",
            str(staged),
            "--only-binary",
            ":all:",
            "--no-progress",
            str(wheel),
        ],
        check=True,
        timeout=300,
    )
    if not (staged / exe_name).is_file():
        raise shared.UpdateError(f"Loom SDK wheel does not install {exe_name}")
    console = next((path for path in sorted(staged.rglob("loom-serve.exe"))), None)
    # - pip writes console scripts beside the packages on Windows and into bin/ elsewhere, so the marker
    #   records whichever path this install produced: a launcher has to name the executable
    installed = {"asset": asset["name"], "console_script": console.relative_to(staged).as_posix() if console else ""}
    (staged / "INSTALL.json").write_text(json.dumps(installed, indent=2) + "\n", encoding="utf-8")
    shared.replace_installation(staged, destination)
