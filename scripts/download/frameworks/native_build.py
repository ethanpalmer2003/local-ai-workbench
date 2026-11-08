"""Shared Windows compiler environment and logged, bounded native build commands."""

import subprocess
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import update_shared as updater


def visual_studio_environment(component_key: str = "shared") -> dict[str, str]:
    vswhere = Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe")
    installation = subprocess.check_output(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
        timeout=30,
    ).strip()
    vcvars = Path(installation) / "VC/Auxiliary/Build/vcvarsall.bat"
    if not vcvars.is_file():
        raise updater.UpdateError("Visual Studio C++ Build Tools are required")
    folder = project_cfg.component(component_key).generated_dir
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "build-environment.cmd"
    script.write_text(f'@echo off\ncall "{vcvars}" x64 >nul\nif errorlevel 1 exit /b 1\nset\n', encoding="utf-8")
    output = subprocess.check_output(["cmd.exe", "/d", "/c", str(script)], text=True, timeout=60)
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line and not line.startswith("="))


def run(command: list[str], log: Path, env: dict[str, str] | None = None, timeout: int = 900) -> None:
    print(subprocess.list2cmdline(command), flush=True)
    with log.open("w", encoding="utf-8") as output:
        subprocess.run(command, env=env, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=timeout)
