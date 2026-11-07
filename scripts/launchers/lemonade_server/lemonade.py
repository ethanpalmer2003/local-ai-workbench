"""Lemonade Server startup, and the config patch that points it at our own weights."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg

HEALTH_ROUTE = "/api/v0/health"
LOG_DIR = project_cfg.component("lemonade_server").logs_dir


def server_command(port: int | None = None) -> list[str]:
    return [str(cfg.LEMONADE_SERVICE.exe), "--port", str(port or cfg.LEMONADE_SERVICE.port)]


def health_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or cfg.LEMONADE_SERVICE.port}{HEALTH_ROUTE}"


@contextmanager
def run_config(models_dir: Path, port: int | None = None) -> Iterator[None]:
    """Serve this run's weights on this run's port, then restore the user's settings."""
    path = cfg.LEMONADE_SERVICE.config
    original = path.read_text(encoding="utf-8")
    settings = json.loads(original)
    settings.update(
        {
            "port": port or cfg.LEMONADE_SERVICE.port,
            # - our GGUF tree, so a comparison loads the same weights every backend does
            "extra_models_dir": str(models_dir),
            # - one server per run: a fixed websocket port would collide with an existing one
            "websocket_port": "auto",
        }
    )
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _answers(port: int) -> bool:
    try:
        return launch_util.backend_ready(health_url(port), timeout=2)
    except (urllib.error.HTTPError, OSError):
        return False


def ready(port: int | None = None, timeout_s: float | None = None) -> bool:
    deadline = time.monotonic() + (timeout_s if timeout_s is not None else cfg.LEMONADE_SERVICE.startup_timeout_s)
    served = port or cfg.LEMONADE_SERVICE.port
    while time.monotonic() < deadline:
        if launch_util.port_listening(served) and _answers(served):
            return True
        time.sleep(0.5)
    return False


def new_log_path() -> Path:
    return LOG_DIR / f"lemonade_{time.strftime('%Y%m%d-%H%M%S')}.log"


def start(models_dir: Path, port: int | None = None) -> tuple[subprocess.Popen[Any], Path]:
    """Start the server on this run's weights; the caller stops it."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = new_log_path()
    process = launch_util.launch_process(
        server_command(port),
        title="Lemonade Server",
        cwd=str(project_cfg.SCRIPTS_DIR),
        report_vram=True,
        log_file=str(log_path),
    )
    if not ready(port):
        launch_util.kill_process_tree(process.pid)
        raise TimeoutError(f"Lemonade Server did not answer {health_url(port)}; see {log_path}")
    return process, log_path


def stop(process: subprocess.Popen[Any], port: int | None = None) -> None:
    launch_util.kill_process_tree(process.pid, ports=port or cfg.LEMONADE_SERVICE.port)
