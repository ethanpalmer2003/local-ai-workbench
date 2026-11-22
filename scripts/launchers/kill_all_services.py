r"""Stop C:\AI-owned processes listening on project service ports."""

import argparse
import os
import socket
import subprocess
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import NamedTuple

import psutil

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import execution_context
from scripts.shared import consent

ROOT = project_cfg.BASE_DIR.resolve()
EXTRA_SERVICE_PORTS = {5551, 8080, 8188}  # Kobold RPC, Strata config, ComfyUI default.
# - Only interpreter/runtime wrappers can run project code while living outside
#   C:\AI. A document argument in a third-party app is not ownership.
PROJECT_RUNTIMES = {"python.exe", "pythonw.exe", "node.exe", "uv.exe"}
AGENT_MARKERS = (
    "coding_agents",
    "command-code",
    "@earendil-works/pi-coding-agent",
    "little-coder",
    "@nanocollective/nanocoder",
    "omp-windows-x64",
    "deepseek harness",
)

PortKey = tuple[str, int]
Ports = set[PortKey]
PortListeners = dict[int, Ports]
ListenerMap = dict[int | None, PortListeners]


class Listener(NamedTuple):
    """One process worth stopping, with the ports it holds."""

    name: str
    ports: Ports


class CandidateScan(NamedTuple):
    """What to stop, and the configured ports whose owner could not be read."""

    candidates: dict[int, Listener]
    unknown: Ports


class Remaining(NamedTuple):
    """One listener still holding a configured port, and whether this run chose to keep it."""

    pid: int | None
    name: str
    related: bool | None
    ports: Ports
    kept: bool


RemainingMap = dict[int, list[Remaining]]


def agent_roots() -> list[Path]:
    """Install and state roots that belong to coding agents or their shared LLM."""
    roots = [
        project_cfg.FRAMEWORKS_DIR / "coding_agents",
        project_cfg.component("llamacpp").framework_dir,
        project_cfg.component("strata").framework_dir,
    ]
    for client in (cfg.PI_CLIENT, cfg.LITTLECODER_CLIENT, cfg.OHMYPI_CLIENT, cfg.NANOCODER_CLIENT):
        roots.extend((client.entry, client.agent_dir))
    roots.extend((cfg.DEEPSEEK_CLIENT.exe, cfg.DEEPSEEK_CLIENT.home))
    return [root.resolve() for root in roots]


def agent_ports() -> set[int]:
    return {cfg.LLAMACPP_SERVICE.port, cfg.LLAMACPP_SERVICE.internal_port, cfg.STRATA_SERVICE.port}


def is_agent_process(info: Mapping[str, object], roots: list[Path]) -> bool:
    """True when the listener belongs to a coding agent, llama.cpp or Strata."""
    cmdline = info.get("cmdline")
    values = [info.get("exe"), info.get("cwd"), *(cmdline if isinstance(cmdline, list) else [])]
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if any(marker in value.casefold() for marker in AGENT_MARKERS):
            return True
        path = Path(value.strip('"'))
        for root in roots:
            try:
                path.resolve().relative_to(root)
                return True
            except (OSError, RuntimeError, ValueError):
                continue
    return False


def configured_ports() -> list[int]:
    """Collect configured service ports, including nested launcher dictionaries."""
    ports = set(EXTRA_SERVICE_PORTS)
    for name, value in vars(cfg).items():
        if not name.isupper():
            continue
        if is_dataclass(value):
            for field in fields(value):
                number = getattr(value, field.name)
                if "port" in field.name.lower() and type(number) is int and 0 < number < 65536:
                    ports.add(number)
        elif isinstance(value, dict):
            for key, number in value.items():
                if "port" in str(key).lower() and type(number) is int and 0 < number < 65536:
                    ports.add(number)
        elif name.endswith("_PORT") and type(value) is int and 0 < value < 65536:
            ports.add(value)
    return sorted(ports)


def in_workspace(value: str | None) -> bool:
    if not value:
        return False
    try:
        Path(value).resolve().relative_to(ROOT)
        return True
    except (OSError, RuntimeError, ValueError):
        root = str(ROOT).replace("/", "\\").rstrip("\\").casefold()
        text = value.strip('"').replace("/", "\\").casefold()
        return root + "\\" in text


def listener_map() -> ListenerMap:
    """Map PID -> local port -> active TCP listeners and UDP sockets."""
    result: ListenerMap = {}
    for connection in psutil.net_connections(kind="inet"):
        if not connection.laddr:
            continue
        if connection.type == socket.SOCK_STREAM and connection.status != psutil.CONN_LISTEN:
            continue
        if connection.type not in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            continue
        protocol = "TCP" if connection.type == socket.SOCK_STREAM else "UDP"
        result.setdefault(connection.pid, {}).setdefault(connection.laddr.port, set()).add(
            (protocol, connection.laddr.port)
        )
    return result


class ProcessIdentity(NamedTuple):
    """A process's display name, whether it belongs to this workspace, and its raw info."""

    name: str
    related: bool | None
    info: dict[str, object]


def process_identity(pid: int) -> ProcessIdentity:
    process = psutil.Process(pid)
    info = process.as_dict(attrs=["name", "exe", "cmdline", "cwd"], ad_value=None)
    name = info.get("name") or info.get("exe") or f"PID {pid}"
    if not any((info.get("exe"), info.get("cwd"), info.get("cmdline"))):
        return ProcessIdentity(name, None, info)
    executable = info.get("exe") or next(iter(info.get("cmdline") or []), "")
    if in_workspace(executable):
        return ProcessIdentity(name, True, info)
    # - Third-party apps can carry a C:\AI document argument, or even cwd there.
    #   Only interpreter/runtime wrappers are project-owned outside the workspace.
    if Path(executable).name.casefold() not in PROJECT_RUNTIMES:
        return ProcessIdentity(name, False, info)
    related = in_workspace(info.get("cwd")) or any(in_workspace(argument) for argument in (info.get("cmdline") or []))
    return ProcessIdentity(name, related, info)


def process_details(pid: int) -> tuple[str, bool | None]:
    name, related, _ = process_identity(pid)
    return name, related


def format_ports(ports: set[tuple[str, int]]) -> str:
    return ", ".join(f"{protocol}/{port}" for protocol, port in sorted(ports))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--non-agents",
        action="store_true",
        help="stop non-agent services only; keep coding agents, llama.cpp and Strata running",
    )
    consent.flag(parser)
    return parser.parse_args()


def report_context() -> int | None:
    """Print the execution token and refuse an environment that hides listeners."""
    context = execution_context()
    token = context["windows_token"]
    app_container = token["app_container"] if token else "unknown"
    elevated = token["administrator_elevated"] if token else "unknown"
    print(f"Execution context: AppContainer={app_container}; administrator elevated={elevated}")
    if app_container is True:
        print(
            "[FAIL] Run from a normal Windows terminal; AppContainer can hide listeners and deny process termination."
        )
        return 2
    return None


def collect_candidates(
    args: argparse.Namespace, configured: set[int], roots: list[Path], keep_ports: set[int]
) -> CandidateScan:
    """C\\AI-owned listeners to stop, plus configured ports whose owner could not be read."""
    try:
        before = listener_map()
    except psutil.AccessDenied as error:
        raise RuntimeError(f"Could not enumerate listening ports: {error}") from error

    candidates: dict[int, Listener] = {}
    unknown: Ports = set()
    for pid, listeners in before.items():
        bound = {(protocol, port) for port, endpoints in listeners.items() for protocol, _ in endpoints}
        if pid is None:
            unknown.update((protocol, port) for protocol, port in bound if port in configured)
            continue
        if args.non_agents and any(port in keep_ports for _, port in bound):
            print(f"[KEEP] agent stack · {format_ports(bound)}", flush=True)
            continue
        try:
            name, related, info = process_identity(pid)
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess):
            unknown.update((protocol, port) for protocol, port in bound if port in configured)
            continue
        if related:
            if args.non_agents and is_agent_process(info, roots):
                print(f"[KEEP] {name} PID {pid} · {format_ports(bound)} (agent stack)", flush=True)
                continue
            candidates[pid] = Listener(name, bound)
        elif related is None:
            unknown.update((protocol, port) for protocol, port in bound if port in configured)
    return CandidateScan(candidates, unknown)


def terminate(candidates: dict[int, Listener]) -> None:
    for pid, listener in sorted(candidates.items()):
        detail = format_ports(listener.ports)
        result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print(f"[KILLED] {listener.name} PID {pid} · {detail}")
        else:
            message = (result.stderr or result.stdout).strip().splitlines()
            print(f"[FAIL] {listener.name} PID {pid} · {detail}" + (f" · {message[-1]}" if message else ""))


def remaining_listeners(args: argparse.Namespace, roots: list[Path], keep_ports: set[int]) -> RemainingMap:
    remaining: RemainingMap = {}
    for pid, listeners in listener_map().items():
        for port, endpoints in listeners.items():
            if pid is None:
                name, related, kept = "Unknown process", None, False
            else:
                try:
                    name, related, info = process_identity(pid)
                    kept = bool(args.non_agents and (port in keep_ports or is_agent_process(info, roots)))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    name, related, kept = f"PID {pid}", None, False
            remaining.setdefault(port, []).append(
                Remaining(pid, name, related, {(protocol, port) for protocol, _ in endpoints}, kept)
            )
    return remaining


def report_remaining(ports: list[int], remaining: RemainingMap, unknown: Ports) -> None:
    print("\nConfigured-port check:")
    for port in ports:
        listeners = remaining.get(port, [])
        if not listeners:
            print(f"[FREE] {port}")
            continue
        for listener in listeners:
            if listener.kept:
                label = "AGENT STACK (kept)"
            else:
                label = (
                    "STILL LISTENING"
                    if listener.related is True
                    else "UNRELATED PROCESS"
                    if listener.related is False
                    else "OWNER UNKNOWN"
                )
            owner = "?" if listener.pid is None else listener.pid
            print(f"[WARN] {port} {label}: {listener.name} PID {owner}")
    for protocol, port in sorted(unknown):
        if port not in remaining:
            print(f"[OK] {protocol}/{port} listener ended before owner details were available.")


def main() -> int:
    args = parse_args()
    if os.name != "nt":
        print("[FAIL] This shutdown launcher supports Windows only.")
        return 2
    context_failure = report_context()
    if context_failure is not None:
        return context_failure
    scope = "non-agent services" if args.non_agents else "every C:\\AI-owned service"
    if not consent.confirm(f"Stop {scope}", args.yes):
        return 1

    ports = configured_ports()
    configured = set(ports)
    roots = agent_roots() if args.non_agents else []
    keep_ports = agent_ports() if args.non_agents else set()
    print(
        f"Checking {len(ports)} configured service ports and all active TCP/UDP listeners for C:\\AI-owned processes."
    )
    if args.non_agents:
        print("Mode          : non-agent services only (coding agents, llama.cpp and Strata are preserved).")
    try:
        candidates, unknown = collect_candidates(args, configured, roots, keep_ports)
    except RuntimeError as error:
        print(f"[FAIL] {error}")
        return 2
    terminate(candidates)

    remaining = remaining_listeners(args, roots, keep_ports)
    report_remaining(ports, remaining, unknown)
    remaining_related = any(
        related is True and not kept for values in remaining.values() for _, _, related, _, kept in values
    )
    return 1 if remaining_related or any(port in configured for _, port in unknown if port in remaining) else 0


if __name__ == "__main__":
    raise SystemExit(main())
