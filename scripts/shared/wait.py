"""The one bounded wait and the one readiness probe; callers supply the condition and the budget."""

import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

# One loop, one probe. A caller that needs something else (a protocol handshake, a stream read,
# a service that runs until interrupted) is a different question and owns its own small loop.


def backend_unavailable(error: BaseException) -> bool:
    """Only these answers mean "down or still starting"; every other failure is a real defect."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (502, 503)
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, (ConnectionRefusedError, TimeoutError))


def http_ready(url: str, *, timeout: float = 1, strict: bool = False) -> bool:
    """Readiness probe; the two callers differ only in what an unexpected answer means.

    - default, for polling: any transport or status problem is "not ready yet", never an error
    - strict, for a reuse decision: only an unavailable backend reads as not ready, so a wrong
      readiness route or a broken server surfaces instead of being polled to the deadline
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
        return True
    except OSError as error:
        if strict and not backend_unavailable(error):
            raise
        return False


def wait_ready(
    ready: Callable[[], bool],
    timeout: float,
    *,
    label: str,
    process: subprocess.Popen[Any] | None = None,
    interval: float = 0.2,
    heartbeat_seconds: float = 10,
    fail: Callable[[], str | None] | None = None,
) -> None:
    """Wait until ready; raise TimeoutError at the budget, RuntimeError when the wait is doomed.

    - process: the owner started by this run; its exit ends the wait immediately.
    - fail: a caller-side abort such as an error collected on another thread.
    - The heartbeat answers what a person watching a slow load actually asks: still progressing?
    """
    if timeout < 0 or interval < 0:
        raise ValueError("Readiness timeout and polling interval cannot be negative")
    started = time.monotonic()
    deadline = started + timeout
    announced = started
    while True:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{label} exited during startup ({process.returncode})")
        if fail is not None and (message := fail()):
            raise RuntimeError(message)
        if ready():
            return
        now = time.monotonic()
        if now - announced >= heartbeat_seconds:
            announced = now
            print(f"[WAIT] {label} still starting: {now - started:.0f} s of {timeout:.0f} s", flush=True)
        remaining = deadline - now
        if remaining <= 0:
            raise TimeoutError(f"{label} did not become ready within {timeout:g} seconds")
        time.sleep(min(interval, remaining))
