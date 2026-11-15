"""The one bounded wait and the one readiness probe; callers supply the condition and the budget."""

import subprocess
import time
from collections.abc import Callable
from typing import Any

import requests

# One loop, one probe. A caller that needs something else (a protocol handshake, a stream read,
# a service that runs until interrupted) is a different question and owns its own small loop.


UNAVAILABLE_STATUSES = (502, 503, 504)


def backend_unavailable(status: int) -> bool:
    """Only these answers mean "down or still starting"; every other status is a real defect."""
    return status in UNAVAILABLE_STATUSES


def http_ready(url: str, *, timeout: float = 1, strict: bool = False) -> bool:
    """Readiness probe; the two callers differ only in what an unexpected answer means.

    - default, for polling: a connection problem or any error status is "not ready yet"
    - strict, for a reuse decision: only a gateway saying its backend is unavailable reads as not
      ready, so a wrong readiness route or a broken server raises instead of polling to the deadline
    """
    try:
        response = requests.get(url, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout):
        return False
    if response.ok:
        return True
    if not strict or backend_unavailable(response.status_code):
        return False
    response.raise_for_status()
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
