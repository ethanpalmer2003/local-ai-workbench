"""Model-free Popen fixtures with explicit state and inspectable mock calls."""

import subprocess
from unittest.mock import MagicMock

_POPEN_SPEC = subprocess.Popen
# Add reusable lifecycle behavior here; individual tests retain scenario assertions.


def fake_process(*, pid: int = 12345, running: bool = True, exit_code: int = 0, wait_timeouts: int = 0) -> MagicMock:
    if wait_timeouts < 0 or (not running and wait_timeouts):
        raise ValueError("An exited process cannot time out waiting; timeout counts must be nonnegative")
    process = MagicMock(spec=_POPEN_SPEC)
    process.pid = pid
    process.args = ["fixture-process"]
    process.returncode = None if running else exit_code
    process.stdin = process.stdout = process.stderr = None
    process.poll.side_effect = lambda: process.returncode
    remaining = wait_timeouts

    def wait(timeout: float | None = None) -> int:
        nonlocal remaining
        if process.returncode is not None:
            return process.returncode
        if remaining and timeout is not None:
            remaining -= 1
            raise subprocess.TimeoutExpired(process.args, timeout)
        if process.returncode is None:
            process.returncode = exit_code
        return process.returncode

    process.wait.side_effect = wait
    process.communicate.return_value = (b"", b"")
    return process


def running_process(*, pid: int = 12345, wait_timeouts: int = 0) -> MagicMock:
    return fake_process(pid=pid, wait_timeouts=wait_timeouts)


def exited_process(*, pid: int = 12345, exit_code: int = 0) -> MagicMock:
    return fake_process(pid=pid, running=False, exit_code=exit_code)


def inspected_process(*, pid: int, parent: int = 0, command=(), children=()) -> MagicMock:
    """Explicit psutil inspection fixture; distinct from Popen lifecycle behavior."""
    import psutil

    process = MagicMock(spec=psutil.Process)
    process.pid = pid
    process.ppid.return_value = parent
    process.cmdline.return_value = list(command)
    process.children.return_value = list(children)
    return process
