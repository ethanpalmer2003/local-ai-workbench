"""Pin a llama.cpp build to the discrete adapter so it cannot silently run on the integrated one."""

import re
import subprocess
from pathlib import Path

from scripts.config.shared import hardware

DEVICE_LINE = re.compile(r"^\s+(\S+): (.+?) \(\d+ MiB", re.MULTILINE)
LIST_TIMEOUT_S = 120


def vulkan_devices(binary: Path) -> list[tuple[str, str]]:
    """Device id and name per the build's own `--list-devices` output."""
    result = subprocess.run(
        [str(binary), "--list-devices"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=LIST_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{binary} --list-devices exited {result.returncode}: {result.stderr.strip()}")
    return DEVICE_LINE.findall(result.stdout)


def discrete_vulkan_device(binary: Path) -> str:
    """The listed device whose name is the tracked discrete adapter; a missing one is an error."""
    wanted = hardware.discrete_gpu().lower()
    for device_id, name in vulkan_devices(binary):
        if wanted in name.lower():
            return device_id
    listed = ", ".join(f"{device_id}: {name}" for device_id, name in vulkan_devices(binary)) or "none"
    raise RuntimeError(f"Vulkan did not list {hardware.discrete_gpu()}; available: {listed}")
