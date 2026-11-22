"""Which GPU an engine may use: resolve the tracked discrete adapter from the engine's own device list.

The standard is the same for every launcher: no tracked file stores a device ordinal, which is only a
position in one runtime's enumeration order. A launcher asks its own binary for the list, matches the name
from `config/shared/hardware.json`, and passes the returned id or index. A missing adapter fails the launch;
falling back to index 0 would silently select the integrated GPU.
"""

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scripts.config.shared import hardware

LIST_TIMEOUT_S = 120
# - llama.cpp on Vulkan: `  Vulkan0: AMD Radeon RX 7800 XT (16368 MiB, 15408 MiB free)`
LLAMA_DEVICE = re.compile(r"^\s+(Vulkan\d+): (.+?) \(\d+ MiB", re.MULTILINE)
# - llama.cpp on ROCm/HIP: `  ROCm0: AMD Radeon RX 7800 XT (16368 MiB, 16222 MiB free)`
HIP_DEVICE = re.compile(r"^\s+(ROCm\d+): (.+?) \(\d+ MiB", re.MULTILINE)
# - sd.cpp: `Vulkan0\tAMD Radeon RX 7800 XT`, printed after its `ggml_vulkan: Found n devices` block
SD_DEVICE = re.compile(r"^(Vulkan\d+)\t(.+?)\s*$", re.MULTILINE)
# - audio.cpp: `Vulkan:0 "AMD Radeon RX 7800 XT" [GPU]`
AUDIO_DEVICE = re.compile(r'^Vulkan:(\d+) "(.+?)" \[', re.MULTILINE)


@dataclass(frozen=True)
class Device:
    """One listed device: the id an engine takes, its position there, and the adapter name."""

    id: str
    name: str
    index: int


def _device_index(device_id: str) -> int:
    """The number in a device id: `Vulkan0` and `ROCm0` both mean position 0."""
    return int("".join(character for character in device_id if character.isdigit()))


def devices(text: str) -> list[Device]:
    """Every GPU adapter a listing names, in the engine's own order."""
    for pattern in (LLAMA_DEVICE, HIP_DEVICE, SD_DEVICE):
        listed = [
            Device(match.group(1), match.group(2).strip(), _device_index(match.group(1)))
            for match in pattern.finditer(text)
        ]
        if listed:
            return listed
    return [Device(f"Vulkan{index}", name.strip(), int(index)) for index, name in AUDIO_DEVICE.findall(text)]


def discrete_from_listing(text: str) -> Device:
    """The listed device whose name is the tracked discrete adapter; a missing one is an error."""
    wanted = hardware.discrete_gpu().lower()
    listed = devices(text)
    for device in listed:
        if wanted in device.name.lower():
            return device
    available = ", ".join(f"{device.id}: {device.name}" for device in listed) or "none"
    raise RuntimeError(f"the engine did not list {hardware.discrete_gpu()}; available: {available}")


def _listing(binary: Path) -> str:
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
    return result.stdout


def device_for_binary(binary: Path) -> Device:
    """The device this binary must be told to use, resolved from its own `--list-devices`."""
    return discrete_from_listing(_listing(binary))


def discrete_device_id(binary: Path) -> str:
    """The device id (VulkanN or ROCmN) for the tracked discrete adapter."""
    return device_for_binary(binary).id


def main(arguments: list[str] | None = None) -> int:
    """Print the resolved device per engine binary; exit 1 when one cannot find the discrete adapter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binaries", nargs="+", help="engine executables that support --list-devices")
    options = parser.parse_args(arguments)
    failed = False
    for name in options.binaries:
        try:
            device = device_for_binary(Path(name))
        except (OSError, RuntimeError) as error:
            print(f"[FAIL] {name}: {error}")
            failed = True
        else:
            print(f"[OK] {name}: {device.id} (index {device.index}) {device.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
