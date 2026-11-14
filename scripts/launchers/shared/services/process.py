"""Shared cleanup and ownership primitives; callers retain ownership/reuse policy."""

import subprocess
from types import SimpleNamespace
from typing import Any

from scripts.launchers import launch_util

# Reuse these primitives; reuse/isolation policy belongs to the calling adapter.
# Readiness lives in scripts.shared.wait, where every role can reach it.


def owned_module_worker(process, module: str):
    """Resolve a Python redirector's real worker only within its owned descendants."""
    import psutil

    root = psutil.Process(process.pid)
    matches = []
    for candidate in (root, *root.children(recursive=True)):
        args = candidate.cmdline()
        if "-m" in args and args[args.index("-m") + 1 : args.index("-m") + 2] == [module]:
            matches.append(candidate)
    parents = {candidate.ppid() for candidate in matches}
    leaves = [candidate for candidate in matches if candidate.pid not in parents]
    if len(leaves) != 1:
        raise RuntimeError(f"Cannot identify one owned module worker for {module}")
    return SimpleNamespace(pid=leaves[0].pid, poll=process.poll)


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
