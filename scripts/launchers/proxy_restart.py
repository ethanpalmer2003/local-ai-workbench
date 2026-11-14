"""Explicit, local-only lifecycle actions supplied by a proxy's owning launcher."""

import hashlib
import importlib
import socket
import subprocess
import traceback
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib.parse import urlsplit


class OwnedBackendLifecycle:
    def __init__(
        self,
        process: subprocess.Popen[Any],
        start: Callable[[], subprocess.Popen[Any]],
        health_url: str,
        prepare: Callable[[], object],
    ) -> None:
        self.process = process
        self.start = start
        self.health_url = health_url
        self.prepare = prepare

    def restart(self) -> None:
        from scripts.launchers.launch_util import kill_process_tree

        self.prepare()
        if self.process.poll() is None:
            kill_process_tree(self.process.pid)
            self.process.wait(timeout=20)
        address = urlsplit(self.health_url)
        with socket.socket() as connection:
            connection.settimeout(0.5)
            if connection.connect_ex((address.hostname or "127.0.0.1", address.port or 80)) == 0:
                raise RuntimeError("Backend port is still occupied; refusing to replace another service")
        self.process = self.start()
        from scripts.shared.wait import http_ready, wait_ready

        wait_ready(
            lambda: http_ready(self.health_url, strict=True),
            90,
            label="restarted backend",
            process=self.process,
            interval=0.5,
        )


def reload_proxy_configuration(service: object, service_name: str) -> None:
    from scripts.launchers import launcher_config as cfg

    bindings = {key: getattr(service, key) for key in ("listen_ip", "port", "internal_port")}
    importlib.reload(cfg)
    updated = getattr(cfg, service_name)
    for field in fields(updated):
        setattr(service, field.name, getattr(updated, field.name))
    # - Rebinding listen ports or backend addresses requires a full launcher relaunch.
    for key, value in bindings.items():
        setattr(service, key, value)
    setattr(cfg, service_name, service)


class ProxyRestartController:
    def __init__(self, callbacks: dict[str, Callable[[], None]], files: dict[str, list[Path]]) -> None:
        self.callbacks = callbacks
        self.files = files
        self.baselines = {(scope, str(path)): self.digest(path) for scope, paths in files.items() for path in paths}
        self.lock = Lock()
        self.state: dict[str, object] = {"status": "idle", "target": None, "error": None}
        self.restart_listener: Callable[[], None] | None = None
        self.listener_requested = False

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"

    def snapshot(self) -> dict[str, object]:
        changed = {
            scope: [str(p) for p in paths if self.digest(p) != self.baselines[(scope, str(p))]]
            for scope, paths in self.files.items()
        }
        scopes = [scope for scope, paths in changed.items() if paths]
        return {
            **self.state,
            "available_targets": [*self.callbacks, *(["both"] if len(self.callbacks) == 2 else [])],
            "changed_files": changed,
            "configuration_files": {scope: [str(p) for p in paths] for scope, paths in self.files.items()},
            "recommended_target": "both" if len(scopes) == 2 else scopes[0] if scopes else None,
            "reasons": {
                "backend": "Session options, model/backend configuration: interrupts generation and unloads models.",
                "proxy": "Proxy configuration: reloads settings and restarts the HTTP listener.",
                "both": "Changes in both configuration groups. Python implementation edits require relaunching the launcher.",
            },
        }

    def start(self, target: str) -> None:
        scopes = ["proxy", "backend"] if target == "both" else [target]
        if any(scope not in self.callbacks for scope in scopes):
            raise ValueError("Restart target is not supported by this launcher")
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("A restart is already running")
        self.state = {"status": "restarting", "target": target, "error": None}
        Thread(target=self._run, args=(scopes,), daemon=True).start()

    def _run(self, scopes: list[str]) -> None:
        try:
            for scope in scopes:
                before = {(scope, str(path)): self.digest(path) for path in self.files.get(scope, [])}
                self.callbacks[scope]()
                self.baselines.update(before)
            if "proxy" in scopes and self.restart_listener:
                self.listener_requested = True
                self.restart_listener()
            self.state = {**self.state, "status": "completed"}
        except Exception as error:
            traceback.print_exc()
            self.state = {**self.state, "status": "failed", "error": str(error)}
        finally:
            self.lock.release()
