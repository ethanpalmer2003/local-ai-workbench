"""Task-owned persistent HTTP process; independent of task, model and native engine."""

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.launchers import launch_util
from scripts.launchers.shared.services.process import http_ready, stop_owned, wait_ready


class ResidentHttp:
    def __init__(
        self,
        command: list[str],
        port: int,
        log: Path,
        *,
        model_identity: str,
        env: dict[str, str] | None = None,
        readiness: str = "/health",
        timeout: float = 60,
        cwd: Path | None = None,
    ):
        self.command, self.port, self.log = command, port, log
        self.model_identity, self.env = model_identity, env
        self.readiness, self.timeout = readiness, timeout
        self.cwd = cwd
        self.process: subprocess.Popen[bytes] | None = None
        self.stream = None
        self.lifecycle = BenchmarkLifecycle(self.identity, self.stop)

    def identity(self) -> str:
        process = self.process
        return f"{process.pid}:{self.model_identity}" if process and process.poll() is None else ""

    def start(self) -> None:
        if Path(self.command[0]).name.lower() == "llama-server.exe" and launch_util.llama_server_running():
            raise RuntimeError("Existing llama.cpp session retained; isolated benchmark not started")
        if launch_util.port_listening(self.port):
            raise RuntimeError(f"Port {self.port} occupied; existing session retained")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.log.open("wb")
        self.process = subprocess.Popen(  # owned: this benchmark stops the server it starts
            self.command,
            cwd=str(self.cwd or Path(self.command[0]).parent),
            env={**os.environ, **(self.env or {})},
            stdout=self.stream,
            stderr=subprocess.STDOUT,
        )
        launch_util.assign_process_to_job(self.process.pid)
        wait_ready(self.process, self.ready, self.timeout, label=f"Server; log: {self.log}", interval=0.1)

    def ready(self) -> bool:
        return http_ready(f"http://127.0.0.1:{self.port}{self.readiness}")

    def post(self, endpoint: str, body: bytes, content_type: str, timeout: float | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{endpoint}", body, {"Content-Type": content_type}
        )
        with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
            return json.load(response)

    def stop(self) -> None:
        try:
            if self.process:
                stop_owned(self.process, timeout=10)
        finally:
            if self.stream:
                self.stream.close()
