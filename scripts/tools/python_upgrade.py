"""Ask uv whether the project's dependencies resolve for another Python version.

Resolution is the cheap half: uv reads every package's `Requires-Python` and fails naming the package
that excludes the candidate. It does not prove wheels exist for that interpreter, so `--install`
builds a throwaway environment and installs into it, which is the only answer that covers compiled
dependencies such as torch and onnxruntime.

Run from `C:/AI`; nothing here edits the project environment.
"""

import argparse
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from scripts.config import project_config as project_cfg

PYPROJECT = project_cfg.BASE_DIR / "pyproject.toml"
# - a resolution that fails usually names the package in one of these forms
CULPRIT = ("requires-python", "Requires-Python", "does not support", "no wheels")


def floor() -> str:
    """The declared interpreter floor, as written in pyproject."""
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(declared["project"]["requires-python"])


def resolves(version: str) -> tuple[bool, str]:
    """Whether uv can resolve the project for this version, with the message that settled it."""
    result = subprocess.run(
        ["uv", "pip", "compile", str(PYPROJECT), "--python-version", version, "--no-header", "--quiet"],
        cwd=project_cfg.BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, f"{len(result.stdout.splitlines())} pinned lines"
    detail = (result.stderr or result.stdout).strip().splitlines()
    blocking = [line for line in detail if any(marker in line for marker in CULPRIT)]
    return False, (blocking[-1] if blocking else detail[-1] if detail else "uv failed without output")


def installs(version: str) -> tuple[bool, str]:
    """Whether a scratch environment on this version installs the project, which proves the wheels."""
    with tempfile.TemporaryDirectory() as folder:
        environment = Path(folder) / "env"
        created = subprocess.run(
            ["uv", "venv", "--python", version, str(environment)], capture_output=True, text=True, check=False
        )
        if created.returncode:
            return False, (created.stderr or created.stdout).strip().splitlines()[-1]
        synced = subprocess.run(
            ["uv", "sync", "--python", str(environment / "Scripts" / "python.exe")],
            cwd=project_cfg.BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        if synced.returncode:
            detail = (synced.stderr or synced.stdout).strip().splitlines()
            return False, detail[-1] if detail else "uv sync failed without output"
    return True, "installed into a scratch environment"


def below_floor(candidate: str) -> bool:
    """Whether the candidate is older than the declared floor, which no resolution can rescue."""
    floor_parts = tuple(int(part) for part in floor().lstrip(">=^~").split(".") if part.isdigit())
    candidate_parts = tuple(int(part) for part in candidate.split(".") if part.isdigit())
    return bool(floor_parts) and candidate_parts[: len(floor_parts)] < floor_parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="candidate version, for example 3.14")
    parser.add_argument("--install", action="store_true", help="also install into a scratch environment")
    args = parser.parse_args(argv)
    candidate = args.version or f"{sys.version_info.major}.{sys.version_info.minor + 1}"
    print(f"interpreter: {sys.version.split()[0]}; declared floor {floor()}; candidate {candidate}")
    if below_floor(candidate):
        print(f"[FAIL] {candidate} is below the declared floor {floor()}; raise requires-python first")
        return 1
    ok, detail = resolves(candidate)
    print(f"[{'OK' if ok else 'FAIL'}] resolves for {candidate}: {detail}")
    if ok and args.install:
        installed, why = installs(candidate)
        print(f"[{'OK' if installed else 'FAIL'}] installs for {candidate}: {why}")
        ok = ok and installed
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
