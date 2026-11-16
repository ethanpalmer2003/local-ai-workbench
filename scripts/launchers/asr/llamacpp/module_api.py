"""The five functions every llama.cpp ASR module exposes, bound to that module's backend.

Two backends share this surface: a caller reaches `command()`, `start()` and the rest by module name,
so both modules had a copy of the same five wrappers. The factory is the one owner of those wrappers;
each module binds it to its own `BACKEND`, which keeps the module API and the copy out of the tree.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, MutableMapping
from typing import Any, NamedTuple

Url = Callable[[], str]
Probe = Callable[[], bool]
Command = Callable[[], list[str]]
Launch = Callable[[], subprocess.Popen[Any] | None]


class BackendSurface(NamedTuple):
    """The five functions a llama.cpp ASR module exposes, in the order callers unpack them."""

    url: Url
    ready: Probe
    command: Command
    matching_server: Probe
    start: Launch


def bind(backend: Any, namespace: MutableMapping[str, Any]) -> BackendSurface:
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

    return BackendSurface(url, ready, command, matching_server, start)
