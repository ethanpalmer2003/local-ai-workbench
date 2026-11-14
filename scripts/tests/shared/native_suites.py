"""Shared guard for native (VRAM) suites: refuse existing sessions and pin the policy."""

import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.kill_all_services import configured_ports

# - every test belongs to one suite: the model-free run, or a native one that starts real processes
SUITES = ("launchers", "backends", "all")


def service_ports(ports: Iterable[int] | None = None) -> list[int]:
    return sorted({int(port) for port in (configured_ports() if ports is None else ports)})


def existing_sessions(ports: Iterable[int] | None = None) -> list[str]:
    sessions = []
    for port in service_ports(ports):
        for pid in launch_util.listening_process_ids(port):
            sessions.append(f"port {port} pid {pid} ({launch_util.describe_process(pid)})")
    return sessions


def refuse_existing_sessions(ports: Iterable[int] | None = None) -> None:
    sessions = existing_sessions(ports)
    if sessions:
        raise RuntimeError(
            "Native tests refuse to stop an existing session; close it first:\n  " + "\n  ".join(sessions)
        )


@contextmanager
def native_policy() -> Iterator[None]:
    """Native suites never replace a listener: occupied ports are an error, not a kill.

    The env var carries the same policy into worker and probe subprocesses.
    """
    previous = cfg.LAUNCH.existing_service_policy
    previous_env = os.environ.get("AI_EXISTING_SERVICE_POLICY")
    previous_browser = os.environ.get("AI_NO_BROWSER")
    cfg.LAUNCH.existing_service_policy = cfg.ExistingServicePolicy.ERROR
    os.environ["AI_EXISTING_SERVICE_POLICY"] = cfg.ExistingServicePolicy.ERROR.value
    os.environ["AI_NO_BROWSER"] = "1"
    try:
        yield
    finally:
        cfg.LAUNCH.existing_service_policy = previous
        if previous_env is None:
            os.environ.pop("AI_EXISTING_SERVICE_POLICY", None)
        else:
            os.environ["AI_EXISTING_SERVICE_POLICY"] = previous_env
        if previous_browser is None:
            os.environ.pop("AI_NO_BROWSER", None)
        else:
            os.environ["AI_NO_BROWSER"] = previous_browser
