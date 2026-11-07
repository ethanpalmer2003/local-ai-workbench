"""Default-suite boundary, not a sandbox: mocks/loopback/codecs remain permitted."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import sys
from threading import RLock
from collections.abc import Iterator
from typing import Any

from scripts.config import project_config as project_cfg

_lock = RLock()
_depth = 0
_installed = False
_fixture_processes = ContextVar("fixture_processes", default=False)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if not _depth:
        return
    if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
        if event == "subprocess.Popen" and _fixture_processes.get():
            # Windows may derive the executable from its command line instead.
            if args[0] is None:
                return
            executable = Path(os.fsdecode(args[0])).absolute()
            if not executable.is_relative_to(project_cfg.FRAMEWORKS_DIR.absolute()):
                return
        raise AssertionError("Real process start in model-free suite: mock it or select an explicit live test")
    if event == "ctypes.dlopen" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).absolute()
        if path.is_relative_to(project_cfg.FRAMEWORKS_DIR.absolute()):
            raise AssertionError("Real framework DLL load in model-free suite: mock the loader or select a live test")


@contextmanager
def model_free_boundary() -> Iterator[None]:
    """Process-wide so temporary fixture threads inherit the same prohibition."""
    global _depth, _installed
    with _lock:
        if not _installed:
            sys.addaudithook(_audit)
            _installed = True
        _depth += 1
    try:
        yield
    finally:
        with _lock:
            _depth -= 1


@contextmanager
def fixture_processes() -> Iterator[None]:
    """Explicit integration tests only: Python/Node/Git fixtures, never model engines.

    This declaration is reviewed with the test; it is not a child-process sandbox.
    """
    token = _fixture_processes.set(True)
    try:
        yield
    finally:
        _fixture_processes.reset(token)
