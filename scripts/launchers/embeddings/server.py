"""Embedding server lifecycle: llama.cpp serving the cataloged embedding model.

One server serves the documentation duplicate check; the model and port come from
`launcher_config.EMBEDDINGS_SERVER`, and an existing matching server is reused.
"""

import subprocess
from typing import Any

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.shared.services import native


def url() -> str:
    return f"http://127.0.0.1:{cfg.EMBEDDINGS_SERVER.port}"


def ready() -> bool:
    return launch_util.backend_ready(url() + "/health")


def command() -> list[str]:
    settings = cfg.EMBEDDINGS_SERVER
    return [
        str(settings.exe),
        "-m",
        str(settings.model),
        "--embeddings",
        "--pooling",
        settings.pooling,
        "--host",
        "127.0.0.1",
        "--port",
        str(settings.port),
        "-c",
        str(settings.context),
        "-b",
        str(settings.batch),
        "-ub",
        str(settings.batch),
        "--parallel",
        "1",
        "-ngl",
        "99",
        "--no-webui",
    ]


def matching_server() -> bool:
    return native.matches(command())


def start() -> subprocess.Popen[Any] | None:
    settings = cfg.EMBEDDINGS_SERVER
    return native.start_server(
        command(),
        (settings.exe, settings.model),
        settings.port,
        "Embedding model",
        ready,
        matching_server,
        int(settings.startup_timeout_s),
        component_key="embeddings",
    )
