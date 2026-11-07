"""Load audio.cpp and record its model/context/memory report."""

import json
import urllib.request

from scripts.benchmarks.shared.reporting import report_run
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import (
    backend_running,
    build_cli_args,
    kill_process_tree,
    launch_process,
    wait_for_backend,
)
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.timing import timed


def get_json(base: str, path: str) -> object:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    output = CasePaths(__file__).new_run()
    with report_run(output, "audiocpp/audiocpp_ctx_probe", "audio-probe"):
        ports = (cfg.AUDIOCPP_SERVICE.internal_port, cfg.AUDIOCPP_SERVICE.port, 18889)
        port = next((port for port in ports if backend_running(port)), 18889)
        base = f"http://127.0.0.1:{port}"
        process = None
        log = output.logs / "server.log"
        try:
            if not backend_running(port):
                command = [
                    str(project_cfg.AUDIOCPP_SERVER_EXE),
                    *build_cli_args({**cfg.AUDIOCPP_SERVER_ARGS, "port": port}),
                ]
                process = launch_process(
                    command,
                    "audio.cpp context probe",
                    cwd=str(project_cfg.AUDIOCPP_BIN_DIR),
                    kill_ports=port,
                    mode=cfg.ConsoleTerminalLaunchMode.MERGE,
                    log_file=str(log),
                )
                if not wait_for_backend(port, 90):
                    raise TimeoutError(f"Audio server did not become ready; see {log}")
            before = get_json(base, "/v1/models")
            request = urllib.request.Request(
                base + "/v1/audio/speech",
                data=json.dumps({"model": cfg.AUDIOCPP_SERVICE.model, "input": "hello"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=300) as response:
                (output.artifacts / "speech.wav").write_bytes(response.read())
            report = {"before": before, "after": get_json(base, "/v1/models")}
            (output.artifacts / "models.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            if process is not None:
                kill_process_tree(process.pid)
                process.wait(timeout=15)
        if log.is_file():
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if any(
                    word in line.lower() for word in ("ctx", "context", "kv", "buffer", "memory", "vram", "allocated")
                ):
                    print(line)
        print(f"[OUTPUT] {output.root}")


if __name__ == "__main__":
    with timed("audiocpp/audiocpp_ctx_probe"):
        main()
