"""Fast prerequisite checks every benchmark runs before it loads a model."""

from collections.abc import Mapping
from pathlib import Path

from scripts.launchers import launch_util


def require_paths(entries: Mapping[str, Path | str]) -> None:
    """Named inputs must exist; a missing file fails now, not after a model load."""
    missing = [f"{name}: {path}" for name, path in entries.items() if not Path(path).is_file()]
    if missing:
        raise FileNotFoundError("Missing benchmark inputs: " + "; ".join(missing))


def require_absent_paths(entries: Mapping[str, Path | str]) -> None:
    for name, path in entries.items():
        if Path(path).exists():
            raise RuntimeError(f"{name} already exists: {path}")


def require_free_ports(ports: Mapping[str, int]) -> None:
    """Ports a run will own must be idle; the caller never waits on someone else's session."""
    busy = [f"{name}: {port}" for name, port in ports.items() if launch_util.port_listening(port)]
    if busy:
        raise RuntimeError("Ports already in use: " + "; ".join(busy))


def announce(label: str) -> None:
    print(f"[PREFLIGHT] {label}: inputs and ports ready", flush=True)
