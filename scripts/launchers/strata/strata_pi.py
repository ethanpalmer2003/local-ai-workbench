"""Run Pi against Strata's inference API, reusing an existing model when possible."""

import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

from scripts.config import paths
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp.llamacpp_coding import prepare_pi_env
from scripts.launchers.runtime.backend_readiness import ready_url

LOG_DIR = project_cfg.component("strata").logs_dir


@dataclass
class StrataConnection:
    config_path: Path
    config: dict[str, Any]
    port: int
    api_key: str

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"


def saved_connections(config_path: Path | None = None) -> list[StrataConnection]:
    if config_path is None and cfg.STRATA_SERVICE.config_path.is_file():
        config_path = cfg.STRATA_SERVICE.config_path
    local_roots = {Path.home() / "AppData" / "Local"}
    if os.environ.get("LOCALAPPDATA"):
        local_roots.add(Path(os.environ["LOCALAPPDATA"]))
    files = (
        [config_path]
        if config_path
        else [
            *sorted((Path.home() / ".strata" / "data" / "native-instances").glob("*.json")),
            *(
                local / "Strata" / "install" / f"strata-{cfg.STRATA_SERVICE.model}.json"
                for local in sorted(local_roots)
            ),
        ]
    )
    connections = []
    for file in files:
        if not file.is_file():
            if config_path:
                raise FileNotFoundError(f"Strata configuration not found: {file}")
            continue
        data = paths.load_json(file)
        aliases = data.get("aliases") or []
        if (
            not config_path
            and cfg.STRATA_SERVICE.model not in aliases
            and data.get("model_name") != cfg.STRATA_SERVICE.model_name
        ):
            continue
        key = os.environ.get("STRATA_API_KEY") or data.get("api_key") or ""
        connections.append(StrataConnection(file, data, int(data.get("port") or cfg.STRATA_SERVICE.port), key))
    if not connections:
        raise FileNotFoundError("No saved Strata model configuration. Prepare the model in Strata or pass --config.")
    return connections


def ready_model(connection: StrataConnection) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {connection.api_key}"} if connection.api_key else {}
    request = urllib.request.Request(ready_url("strata", connection.port), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            models = json.load(response).get("data", [])
    except HTTPError as error:
        if error.code == 503:
            return None
        raise RuntimeError(
            f"Strata API on port {connection.port} returned HTTP {error.code}; check its API key."
        ) from None
    except (URLError, TimeoutError):
        return None
    names = {connection.config["model_name"], *(connection.config.get("aliases") or [])}
    model = next((model for model in models if model.get("id") in names), None)
    if model is None:
        raise RuntimeError(f"Port {connection.port} serves a different model; no process was stopped.")
    return model


def prepare_backend(connection: StrataConnection) -> StrataConnection:
    if any(connection.config.get(key) for key in ("mcp_servers", "mcpServers")):
        raise ValueError("Strata config contains MCP servers. Use --config with a backend-only native config.")
    key = os.environ.get("STRATA_API_KEY") or secrets.token_hex(32)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return StrataConnection(connection.config_path, connection.config, cfg.STRATA_SERVICE.port, key)


def start_backend(connection: StrataConnection, log_file: Path | None = None) -> subprocess.Popen[Any]:
    from scripts.launchers import launch_util

    control = cfg.STRATA_SERVICE.control_dir
    python = control / "python" / "python.exe"
    if not python.is_file():
        raise FileNotFoundError(f"Strata's bundled Python was not found: {python}")
    # - the config's own engine switches (WMMA, PREFILL_MMQ, ...) reach the engine
    engine_env = {str(key): str(value) for key, value in (connection.config.get("env") or {}).items()}
    return launch_util.launch_process(
        [
            str(python),
            str(control / "serve" / "server.py"),
            "--engine",
            "strata",
            "--config",
            str(paths.materialize(connection.config_path, folder="strata")),
            "--host",
            "127.0.0.1",
            "--port",
            str(connection.port),
        ],
        title="Strata backend",
        cwd=str(control),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log_file or LOG_DIR / "pi-server.log"),
        env={
            **engine_env,
            "STRATA_API_KEY": connection.api_key,
            "PYTHONHOME": None,
            "PYTHONPATH": None,
            "VIRTUAL_ENV": None,
        },
    )


def wait_for_model(connection: StrataConnection, process: subprocess.Popen[Any]) -> dict[str, Any]:
    deadline = time.monotonic() + cfg.STRATA_SERVICE.startup_timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Strata exited with code {process.returncode}; see {LOG_DIR / 'pi-server.log'}")
        model = ready_model(connection)
        if model:
            return model
        time.sleep(1)
    raise TimeoutError(f"Strata did not become ready; see {LOG_DIR / 'pi-server.log'}")


def pi_command(connection: StrataConnection, model: dict[str, Any]) -> list[str]:
    path = cfg.PI_CLIENT.agent_dir / "models.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    context = int(model.get("meta", {}).get("n_ctx") or 65536)
    inputs = model.get("architecture", {}).get("input_modalities", ["text"])
    data.setdefault("providers", {})["strata"] = {
        "baseUrl": connection.base_url,
        "api": "openai-completions",
        "apiKey": "${STRATA_API_KEY}",
        "models": [
            {
                "id": model["id"],
                "name": "Swift 1.5 (Strata)",
                "reasoning": True,
                "input": inputs,
                "contextWindow": context,
                "maxTokens": min(16384, context),
                "compat": {"supportsReasoningEffort": False},
            }
        ],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [
        cfg.PI_CLIENT.node_cmd,
        str(cfg.PI_CLIENT.entry),
        *cfg.PI_CLIENT.cli_args,
        "--provider",
        "strata",
        "--model",
        model["id"],
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Saved Strata model configuration (default: discover Swift)")
    parser.add_argument("--no-start", action="store_true", help="Require an already running Strata backend")
    parser.add_argument("client_args", nargs=argparse.REMAINDER, help="Pi options after --")
    args = parser.parse_args(argv)
    from scripts.launchers import launch_util
    from scripts.launchers.runtime.execution_context import execution_context

    print("[strata_pi] Execution context: " + json.dumps(execution_context()), flush=True)
    connections = saved_connections(args.config)
    connection = max(connections, key=lambda saved: saved.config_path.stat().st_mtime_ns)
    model = None
    for candidate in connections:
        model = ready_model(candidate)
        if model:
            connection = candidate
            break
        if launch_util.backend_running(candidate.port):
            raise RuntimeError(f"Port {candidate.port} is occupied but not ready. Finish loading Strata and retry.")
    process = None
    try:
        if model is None:
            if args.no_start:
                raise RuntimeError("Strata is not ready. Load the model in Strata or omit --no-start.")
            if launch_util.backend_running(cfg.STRATA_SERVICE.port):
                raise RuntimeError(f"Port {cfg.STRATA_SERVICE.port} is occupied; no process was stopped.")
            connection = prepare_backend(connection)
            print(f"[strata_pi] Starting backend; log: {LOG_DIR / 'pi-server.log'}", flush=True)
            process = start_backend(connection)
            model = wait_for_model(connection, process)
        else:
            print(f"[strata_pi] Reusing {connection.base_url}", flush=True)
        env = prepare_pi_env()
        env["STRATA_API_KEY"] = (
            connection.api_key if connection.api_key and connection.api_key.lower() != "none" else "noop"
        )
        client_args = args.client_args[1:] if args.client_args[:1] == ["--"] else args.client_args
        subprocess.run([*pi_command(connection, model), *client_args], cwd=project_cfg.BASE_DIR, env=env, check=True)
    finally:
        if process is not None and process.poll() is None:
            launch_util.kill_process_tree(process.pid, ports=connection.port)
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
