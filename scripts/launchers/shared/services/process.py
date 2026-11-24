"""Shared cleanup and ownership primitives; callers retain ownership/reuse policy."""

import subprocess
from types import SimpleNamespace
from typing import Any

import psutil

from scripts.launchers import launch_util

# Reuse these primitives; reuse/isolation policy belongs to the calling adapter.
# Readiness lives in scripts.shared.wait, where every role can reach it.


def owned_module_worker(process, module: str):
    """Resolve a Python redirector's real worker only within its owned descendants."""

    root = psutil.Process(process.pid)
    matches = []
    for candidate in (root, *root.children(recursive=True)):
        try:
            args = candidate.cmdline()
            parent = candidate.ppid()
        except psutil.Error:
            # - a worker that exited between the tree walk and the read is not a candidate
            continue
        if "-m" in args and args[args.index("-m") + 1 : args.index("-m") + 2] == [module]:
            matches.append((candidate.pid, parent))
    parents = {parent for _pid, parent in matches}
    leaves = [pid for pid, _parent in matches if pid not in parents]
    if len(leaves) != 1:
        raise RuntimeError(f"Cannot identify one owned module worker for {module}")
    return SimpleNamespace(pid=leaves[0], poll=process.poll)


def stop_owned(
    process: subprocess.Popen[Any],
    *,
    title: str = "service",
    timeout: float = 15,
    graceful: bool = False,
    kill_timeout: float = 5,
) -> None:
    """Only call with a process started/owned by the current operation; the exit status is printed."""
    launch_util.stop_process(process, title, timeout=timeout, graceful=graceful, kill_timeout=kill_timeout)
