"""Shared readiness and cleanup primitives; callers retain ownership/reuse policy."""

import subprocess
import time
import urllib.request
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from scripts.launchers import launch_util

# Reuse these primitives; reuse/isolation policy belongs to the calling adapter.


def owned_module_worker(process, module: str):
    """Resolve a Python redirector's real worker only within its owned descendants."""
    import psutil

    root = psutil.Process(process.pid)
    matches = []
    for candidate in (root, *root.children(recursive=True)):
        args = candidate.cmdline()
        if "-m" in args and args[args.index("-m") + 1:args.index("-m") + 2] == [module]:
            matches.append(candidate)
    parents = {candidate.ppid() for candidate in matches}
    leaves = [candidate for candidate in matches if candidate.pid not in parents]
    if len(leaves) != 1:
        raise RuntimeError(f"Cannot identify one owned module worker for {module}")
    return SimpleNamespace(pid=leaves[0].pid, poll=process.poll)


def http_ready(url: str, *, timeout: float = 1) -> bool:
    """Polling probe: an HTTP/socket failure is not-ready; no response is forwarded."""
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def wait_ready(
    process: subprocess.Popen[Any],
    ready: Callable[[], bool],
    timeout: float,
    *,
    label: str = "Server",
    interval: float = 0.2,
) -> None:
    if timeout <= 0 or interval <= 0:
        raise ValueError("Readiness timeout and polling interval must be positive")
    deadline = time.monotonic() + timeout
    while True:
        if process.poll() is not None:
            raise RuntimeError(f"{label} exited during startup ({process.returncode})")
        if ready():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{label} did not become ready within {timeout:g} seconds")
        time.sleep(min(interval, remaining))


def stop_owned(
    process: subprocess.Popen[Any], *, timeout: float = 15, graceful: bool = False, kill_timeout: float = 5
) -> None:
    """Only call with a process started/owned by the current operation."""
    if process.poll() is not None:
        process.wait(timeout=timeout)
        return

    if graceful:
        process.terminate()
    else:
        launch_util.kill_process_tree(process.pid)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        launch_util.kill_process_tree(process.pid)
        process.wait(timeout=kill_timeout)
