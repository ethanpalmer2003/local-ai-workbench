"""Health-checked, task-owned native process startup."""

import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.shared.services.process import wait_ready, stop_owned


def matches(command: list[str]) -> bool:
    import psutil

    return any(
        process.info["exe"]
        and process.info["cmdline"]
        and Path(process.info["exe"]).resolve() == Path(command[0]).resolve()
        and process.info["cmdline"][1:] == command[1:]
        for process in psutil.process_iter(["exe", "cmdline"])
    )


def start_server(
    command: list[str],
    files: Sequence[Path],
    port: int,
    title: str,
    ready: Callable[[], bool],
    matching: Callable[[], bool],
    timeout: int = 120,
    env: Mapping[str, str | None] | None = None,
    component_key: str = "shared",
) -> subprocess.Popen[Any] | None:
    # - Never stop an existing service: reuse it when it matches, otherwise
    #   refuse. Port clearing belongs to explicit launcher opt-in, not a
    #   health-checked startup path (which tests and Pi sessions share).
    if ready():
        if matching():
            print(f"Reusing healthy {title} on port {port}")
            return None
        raise RuntimeError(f"Existing {title} on port {port} does not match this launch; preserving it")
    if launch_util.port_listening(port):
        raise RuntimeError(f"Port {port} is occupied; existing {title} session is preserved")
    for file in files:
        if not file.is_file():
            raise FileNotFoundError(f"Service dependency missing: {file}; see scripts/launchers/asr/README.md")
    logs = project_cfg.component(component_key).logs_dir
    logs.mkdir(parents=True, exist_ok=True)
    process = launch_util.launch_process(
        command,
        title,
        cwd=str(Path(command[0]).parent),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(logs / f"{title.lower().replace(' ', '-')}_{time.time_ns()}.log"),
        env=env,
    )
    try:
        wait_ready(process, ready, timeout, label=f"{title}; logs: {logs}")
    except BaseException:
        stop_owned(process)
        raise
    return process
