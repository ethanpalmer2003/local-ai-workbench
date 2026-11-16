"""The five functions every llama.cpp ASR module exposes, bound to that module's backend.

Two backends share this surface: a caller reaches `command()`, `start()` and the rest by module name,
so both modules had a copy of the same five wrappers. The factory is the one owner of those wrappers;
each module binds it to its own `BACKEND`, which keeps the module API and the copy out of the tree.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, MutableMapping
from typing import Any


def bind(
    backend: Any, namespace: MutableMapping[str, Any]
) -> tuple[
    Callable[[], str],
    Callable[[], bool],
    Callable[[], list[str]],
    Callable[[], bool],
    Callable[[], subprocess.Popen[Any] | None],
]:
    """Bind (url, ready, command, matching_server, start) to one backend instance.

    `start` reads the probes out of `namespace` rather than closing over them, because the module
    attribute is the seam a caller patches to steer startup without touching the backend.
    """

    def url() -> str:
        return backend.url()

    def ready() -> bool:
        return backend.ready()

    def command() -> list[str]:
        return backend.command()

    def matching_server() -> bool:
        return backend.matching_server()

    def start() -> subprocess.Popen[Any] | None:
        return backend.start(namespace["ready"], namespace["matching_server"])

    return url, ready, command, matching_server, start
