"""Delegate Strata updates to its signature-verifying native updater."""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.download.frameworks.update_shared import UpdateError
from scripts.launchers import launcher_config as cfg

SETUP_PATTERN = re.compile(r"^Strata-(?P<version>.+)-windows-x64-setup\.exe$")


def update_command(destination: Path, check_only: bool) -> list[str]:
    control = destination / "control"
    version = json.loads((destination / "host/package.json").read_text(encoding="utf-8"))["version"]
    command = [
        str(control / "python/python.exe"),
        str(control / "strata.py"),
        "update",
        "--app",
        "--app-version",
        version,
        "--components-dir",
        str(project_cfg.STATE_DIR / "strata/desktop/components"),
        "--model-config",
        str(cfg.STRATA_SERVICE.config_path),
    ]
    if check_only:
        command.extend(["--check", "--output", "json"])
    return command


def describe(part: str, data: dict[str, Any]) -> str:
    installed, offered = data.get("installed"), data.get("offered")
    if isinstance(installed, dict):
        installed = installed.get("version")
    if isinstance(offered, dict):
        offered = offered.get("version")
    versions = str(installed or "not installed")
    if offered and offered != installed:
        versions += f" -> {offered}"
    return f"{part}: {versions}" if data["status"] == "current" else f"{part}: {versions} ({data['status']})"


def app_installers() -> list[Path]:
    """Verified desktop-app installers the native updater left behind, oldest first."""
    folder = project_cfg.STATE_DIR / "strata/desktop/components/.updates/app"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("Strata-*-setup.exe"), key=lambda path: path.stat().st_mtime)


def installed_app_version(destination: Path) -> str:
    return json.loads((destination / "host/package.json").read_text(encoding="utf-8"))["version"]


def version_key(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version)
    return tuple(int(number) for number in numbers) if numbers else (0,)


def installer_version(path: Path) -> str | None:
    match = SETUP_PATTERN.match(path.name)
    return match.group("version") if match else None


def install_app(destination: Path) -> str | None:
    """Run the newest verified app installer silently and confirm the installed version."""
    installed = installed_app_version(destination)
    candidates = [
        (path, version)
        for path in app_installers()
        if (version := installer_version(path)) is not None and version_key(version) > version_key(installed)
    ]
    if not candidates:
        print(f"Desktop app: {installed} is current")
        return None
    installer, version = candidates[-1]
    print(f"Desktop app: installing {version} from {installer.name}")
    subprocess.run([str(installer), "/S", f"/D={destination}"], check=True, timeout=900)
    installed = installed_app_version(destination)
    if installed != version:
        raise UpdateError(f"Strata app installer left {installed} installed, expected {version}")
    print(f"Desktop app: {installed} installed")
    for stale in app_installers():
        if stale != installer:
            stale.unlink(missing_ok=True)
    return installed


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "STRATA_NO_ACQUIRE"):
        environment.pop(name, None)
    return environment


def _tail(text: str, count: int = 15) -> str:
    return "".join(text.splitlines(keepends=True)[-count:])


def _report(text: str) -> dict[str, Any]:
    try:
        report = json.loads(text)
    except json.JSONDecodeError as error:
        raise subprocess.SubprocessError(f"Invalid Strata update report: {text[:500]}") from error
    if not isinstance(report, dict) or any(
        not isinstance(report.get(part), dict) or not isinstance(report[part].get("status"), str)
        for part in ("engine", "control", "app")
    ):
        raise subprocess.SubprocessError("Incomplete Strata update report")
    print("Native update metadata:\n" + json.dumps(report, indent=2))
    for part in ("engine", "control", "app"):
        print(describe(part, report[part]))
    return report


def _stream(command: list[str], cwd: Path, environment: dict[str, str]) -> None:
    """Run the native updater while echoing its output and keeping the tail for a failure."""
    process = subprocess.Popen(
        command, cwd=cwd, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
    )
    if process.stdout is None:
        raise subprocess.SubprocessError("strata update produced no output stream")
    tail: list[str] = []
    for line in process.stdout:
        print(line, end="", flush=True)
        tail = [*tail[-15:], line]
    code = process.wait()
    if code != 0:
        raise subprocess.SubprocessError(f"strata update exited {code}; last output:\n{''.join(tail)}")


def process(destination: Path, check_only: bool) -> dict[str, Any] | None:
    environment = _environment()
    command = update_command(destination, check_only)
    if check_only:
        result = subprocess.run(
            command,
            cwd=destination / "control",
            env=environment,
            check=False,
            timeout=180,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise subprocess.SubprocessError(
                f"strata update exited {result.returncode}:\n{_tail(result.stdout or result.stderr or '')}"
            )
        return _report(result.stdout)
    _stream(command, destination / "control", environment)
    # - Strata's own CLI fetches and verifies the installer but has no install switch,
    #   so the framework updater runs it silently and checks the resulting version.
    install_app(destination)
    return None
