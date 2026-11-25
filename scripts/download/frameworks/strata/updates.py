"""Report Strata's versions from its own updater; installing stays with the app.

Strata updates its engine, control and desktop app as one signed bundle, and the vendor's own
updater refuses to swap an engine whose test start fails. Splitting that decision from the
framework update keeps a half-applied bundle out of this repository: the check runs here, and the
person updates in the app.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from scripts.config import paths
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg


def update_command(destination: Path) -> list[str]:
    """The native check command; `--check --output json` makes it read the feed and change nothing."""
    control = destination / "control"
    version = json.loads((destination / "host/package.json").read_text(encoding="utf-8"))["version"]
    return [
        str(control / "python/python.exe"),
        str(control / "strata.py"),
        "update",
        "--app",
        "--app-version",
        version,
        "--components-dir",
        str(project_cfg.STATE_DIR / "strata/desktop/components"),
        "--model-config",
        # - the tracked config carries {AI_ROOT}; Strata's test start needs real paths
        str(paths.materialize(cfg.STRATA_SERVICE.config_path, folder="strata")),
        "--check",
        "--output",
        "json",
    ]


def describe(part: str, data: dict[str, Any]) -> str:
    """One part as `engine 0.1.59->0.1.63`; the arrow marks an update, so no status word repeats it."""
    installed, offered = data.get("installed"), data.get("offered")
    if isinstance(installed, dict):
        installed = installed.get("version")
    if isinstance(offered, dict):
        offered = offered.get("version")
    versions = str(installed or "not installed")
    if offered and offered != installed:
        versions += f"->{offered}"
    status = "" if data["status"] in ("current", "available") else f" {data['status']}"
    return f"{part} {versions}{status}"


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
    print(", ".join(describe(part, report[part]) for part in ("engine", "control", "app")))
    return report


def process(destination: Path) -> dict[str, Any] | None:
    """Read the native feed through a check-only run; no part is downloaded or installed here."""
    result = subprocess.run(
        update_command(destination),
        cwd=destination / "control",
        env=_environment(),
        check=False,
        timeout=180,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(
            f"strata update --check exited {result.returncode}:\n{_tail(result.stdout or result.stderr or '')}"
        )
    return _report(result.stdout)
