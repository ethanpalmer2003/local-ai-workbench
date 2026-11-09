"""Check and update the local toolchains: npm, uv and pip.

Kept separate from the framework catalog because they live outside C:/AI (global npm, the uv
binary, the scripts venv), but they are versioned the same way: report what is installed
against what the registry offers, then update only what is behind.
"""

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
TAIL = 8


@dataclass
class Toolchain:
    name: str
    installed: list[str]
    latest: Callable[[], str | None]
    update: list[str]


@dataclass
class Row:
    name: str
    current: str
    latest: str
    status: str


def _exe(name: str) -> str:
    return shutil.which(name) or name


def _run(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        return 1, str(error)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _version(text: str) -> tuple[int, ...] | None:
    match = VERSION.search(text)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _pypi_latest(package: str) -> str | None:
    try:
        response = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=15)
        response.raise_for_status()
        return str(response.json()["info"]["version"])
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def _npm_latest() -> str | None:
    code, output = _run([_exe("npm"), "view", "npm", "version"])
    return output.strip().splitlines()[-1] if code == 0 and output.strip() else None


def toolchains() -> list[Toolchain]:
    python = str(Path(sys.executable))
    return [
        Toolchain("npm", [_exe("npm"), "--version"], _npm_latest, [_exe("npm"), "install", "-g", "npm@latest"]),
        Toolchain("uv", [_exe("uv"), "--version"], lambda: _pypi_latest("uv"), [_exe("uv"), "self", "update"]),
        Toolchain(
            "pip",
            [python, "-m", "pip", "--version"],
            lambda: _pypi_latest("pip"),
            [python, "-m", "pip", "install", "--upgrade", "pip"],
        ),
    ]


def _row(tool: Toolchain) -> Row:
    first = tool.installed[0]
    if shutil.which(first) is None and not Path(first).is_file():
        return Row(tool.name, "-", "-", "missing")
    code, output = _run(tool.installed)
    current = _version(output)
    if code != 0 or current is None:
        return Row(tool.name, "-", "-", "unknown")
    return Row(tool.name, ".".join(map(str, current)), "", "checking")


def check() -> list[Row]:
    print("\n=== TOOLCHAINS ===")
    rows: list[Row] = []
    for tool in toolchains():
        row = _row(tool)
        current = _version(row.current)
        latest = _version(tool.latest() or "") if row.status == "checking" else None
        if row.status == "missing":
            print(f"- {row.name}: not installed")
        elif current is None or latest is None:
            row.status = "unknown"
            print(f"- {row.name}: {row.current} (latest unavailable)")
        else:
            row.latest = ".".join(map(str, latest))
            row.status = "available" if latest > current else "current"
            suffix = f" -> {row.latest} (update available)" if row.status == "available" else ""
            print(f"- {row.name}: {row.current}{suffix}")
        rows.append(row)
    return rows


def apply(rows: list[Row]) -> bool:
    selected = [row for row in rows if row.status == "available"]
    if not selected:
        return False
    print("\n=== UPDATING TOOLCHAINS ===")
    failed = False
    by_name = {tool.name: tool for tool in toolchains()}
    for row in selected:
        tool = by_name[row.name]
        print(f"Updating {row.name} ({row.current} -> {row.latest})")
        code, output = _run(tool.update)
        if output.strip():
            print("\n".join(output.splitlines()[-TAIL:]))
        if code != 0:
            print(f"Status: FAILED; {row.name} update exited {code}")
            failed = True
            continue
        print(f"Status: UPDATED {row.name} -> {row.latest}")
    return failed
