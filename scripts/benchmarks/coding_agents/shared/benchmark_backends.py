"""Managed inference endpoints for identical coding-harness tasks."""

import contextlib
import json
import socket
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.paths import RunPaths
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import llamacpp
from scripts.launchers.strata import strata_pi


@dataclass
class BenchmarkEndpoint:
    backend: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    context_window: int = 32768
    max_tokens: int = 16384
    metadata: dict[str, Any] = field(default_factory=dict)

    def provider(self) -> dict[str, Any]:
        return {
            "baseUrl": self.base_url,
            "api": "openai-completions",
            "apiKey": self.api_key or "noop",
            "models": [
                {
                    "id": self.model,
                    "name": self.model,
                    "reasoning": True,
                    "input": ["text"],
                    "contextWindow": self.context_window,
                    "maxTokens": self.max_tokens,
                    "compat": {"supportsReasoningEffort": False},
                }
            ],
        }


def benchmark_llama_config(
    overrides: dict[str, str], profile: str = "swift15", build: str | None = None
) -> llamacpp.LlamaConfig:
    conf = llamacpp.LlamaConfig(profile_name=profile, build_name=build, ini_overrides=overrides)
    conf.profile = replace(conf.profile, extra_args={**conf.profile.extra_args, **overrides})
    return conf


def port_in_use(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def free_ports(ports: int | list[int], label: str) -> None:
    """A benchmark run owns the host: whatever holds its ports is stopped, not reported."""
    for port in [ports] if isinstance(ports, int) else ports:
        if port_in_use(port):
            pids = launch_util.listening_process_ids(port)
            print(f"[INFO] Stopping {label} on port {port}: {', '.join(str(pid) for pid in pids) or 'unknown'}")
            launch_util.kill_processes_on_ports(port)


def preflight(conf: llamacpp.LlamaConfig, backends: list[str], config_path: Path | None = None) -> None:
    if "llamacpp" in backends or "avalon" in backends:
        free_ports(conf.port, "llama.cpp model")
    try:
        connections = strata_pi.saved_connections(config_path)
    except FileNotFoundError:
        if "strata" in backends:
            raise
        connections = []
    free_ports(sorted({cfg.STRATA_SERVICE.port, *(item.port for item in connections)}), "Strata backend")


@contextlib.contextmanager
def llama_endpoint(conf: llamacpp.LlamaConfig, output: RunPaths) -> Iterator[BenchmarkEndpoint]:
    from scripts.shared.http_server import request

    free_ports(conf.port, "llama.cpp server")
    settings = {**conf.get_ini(), **conf.profile.extra_args}
    started = time.perf_counter()
    process = llamacpp.launch(
        conf=conf, mode=cfg.ConsoleTerminalLaunchMode.MERGE, log_dir=output.logs / "llamacpp", clear_port=False
    )
    process_started = launch_util.process_start_time(process.pid)
    try:
        status, body, _ = request(f"http://127.0.0.1:{conf.port}/v1/models", timeout=10)
        if status != 200 or conf.alias not in [entry["id"] for entry in json.loads(body)["data"]]:
            raise RuntimeError("Server model does not match the benchmark model")
        yield BenchmarkEndpoint(
            "llamacpp",
            conf.alias,
            f"http://127.0.0.1:{conf.port}/v1",
            cfg.LLAMACPP_API_KEY_NOOP,
            int(settings["ctx-size"]),
            metadata={
                "build": str(conf.build_dir),
                "profile": conf.name,
                "model_file": str(conf.model),
                "settings": settings,
                "reused": False,
                "startup_seconds": time.perf_counter() - started,
                "command": conf.build_cmd(output.logs / "llamacpp-native.log"),
            },
        )
    finally:
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        launch_util.sweep_escaped_children(conf.port, process_started)
        process.wait(timeout=15)


def strata_config(
    source: strata_pi.StrataConnection, output: RunPaths, conf: llamacpp.LlamaConfig
) -> strata_pi.StrataConnection:
    data: dict[str, Any] = {
        **source.config,
        "host": "127.0.0.1",
        "port": cfg.STRATA_SERVICE.port,
        "open_browser": False,
        "log": str(output.logs / "strata-engine.log"),
        "api_key": source.api_key,
    }
    for key in ("mcp_servers", "mcpServers", "mcp"):
        data.pop(key, None)
    args = list(data["args"])
    context = conf.ini_overrides["ctx-size"]
    if "--max-context" in args:
        args[args.index("--max-context") + 1] = context
    else:
        args += ["--max-context", context]
    data["args"] = args
    data["reasoning_budget_tokens"] = int(conf.ini_overrides["reasoning-budget"])
    if conf.ini_overrides.get("reasoning") == "off":
        data["reasoning_effort"] = "none"
    elif conf.ini_overrides.get("reasoning-effort"):
        data["reasoning_effort"] = conf.ini_overrides["reasoning-effort"]
    path = output.temp / "strata-server.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return strata_pi.StrataConnection(path, data, cfg.STRATA_SERVICE.port, source.api_key)


@contextlib.contextmanager
def strata_endpoint(
    conf: llamacpp.LlamaConfig, output: RunPaths, config_path: Path | None = None
) -> Iterator[BenchmarkEndpoint]:
    import secrets

    connections = strata_pi.saved_connections(config_path)
    free_ports(sorted({cfg.STRATA_SERVICE.port, *(item.port for item in connections)}), "Strata backend")
    source = max(connections, key=lambda item: item.config_path.stat().st_mtime_ns)
    source.api_key = secrets.token_hex(32)
    connection = strata_config(source, output, conf)
    # Runtime paths are scoped to this run; normal Pi/Strata launcher state is not rewritten.
    control = cfg.STRATA_SERVICE.control_dir
    command = [
        str(control / "python" / "python.exe"),
        str(control / "serve" / "server.py"),
        "--engine",
        "strata",
        "--config",
        str(connection.config_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(connection.port),
    ]
    started = time.perf_counter()
    process = launch_util.launch_process(
        command,
        title="Strata benchmark",
        cwd=str(control),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(output.logs / "strata-server.log"),
        env={"STRATA_API_KEY": source.api_key, "PYTHONHOME": None},
    )
    process_started = launch_util.process_start_time(process.pid)
    try:
        model = strata_pi.wait_for_model(connection, process)
        metadata = {
            "source_config": str(source.config_path),
            "model_file": next((value for value in connection.config["args"] if str(value).endswith(".gguf")), None),
            "args": connection.config["args"],
            "startup_seconds": time.perf_counter() - started,
            "reused": False,
            "context_window": int(conf.ini_overrides["ctx-size"]),
            "reasoning_effort": connection.config.get("reasoning_effort"),
            "reasoning_budget": connection.config["reasoning_budget_tokens"],
        }
        yield BenchmarkEndpoint(
            "strata",
            model["id"],
            connection.base_url,
            connection.api_key,
            int(model.get("meta", {}).get("n_ctx") or conf.ini_overrides["ctx-size"]),
            metadata=metadata,
        )
    finally:
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        launch_util.sweep_escaped_children(connection.port, process_started)
        process.wait(timeout=15)


@contextlib.contextmanager
def avalon_endpoint(conf: llamacpp.LlamaConfig, output: RunPaths) -> Iterator[BenchmarkEndpoint]:
    from scripts.benchmarks.inference_engines.engines import avalon

    port = cfg.LLAMACPP_SERVICE.port
    free_ports(port, "llama.cpp/Avalon server")
    for check in (avalon.server_exe(), avalon.model_path(), avalon.mtp_path()):
        if not check.is_file():
            raise RuntimeError(f"Avalon component missing: {check}")
    ctx = str(conf.ini_overrides["ctx-size"])
    argv = [
        str(avalon.server_exe()),
        "-m",
        str(avalon.model_path()),
        "-md",
        str(avalon.mtp_path()),
        "--alias",
        avalon.ALIAS,
        "-c",
        ctx,
        "-b",
        "9536",
        "-ub",
        "9536",
        "-fa",
        "on",
        "-ctk",
        "q8_0",
        "-ctv",
        "q8_0",
        "--spec-type",
        "draft-mtp",
        "--spec-draft-n-max",
        "2",
        "-ubd",
        "256",
        "-ctkd",
        "q8_0",
        "-ctvd",
        "q8_0",
        "--moe-cache",
        "auto",
        "--cache-ram",
        avalon.CACHE_RAM_MIB,
        "--fit",
        "on",
        "--jinja",
        "--parallel",
        "1",
        "--host",
        cfg.LLAMACPP_SERVICE.listen_ip,
        "--port",
        str(port),
        "-lv",
        str(cfg.LLAMACPP_SERVICE.verbosity),
        "--log-file",
        str(output.logs / "avalon-server.log"),
    ]
    started = time.perf_counter()
    process = launch_util.launch_process(
        argv,
        "Avalon benchmark",
        cwd=str(avalon.server_exe().parent),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(output.logs / "avalon-server.log"),
        env=avalon.ENV,
    )
    process_started = launch_util.process_start_time(process.pid)
    try:
        from scripts.shared.wait import http_ready, wait_ready

        wait_ready(
            lambda: http_ready(f"http://127.0.0.1:{port}/health", timeout=2),
            300,
            label="Avalon",
            process=process,
            interval=1,
        )
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as response:
            models = json.load(response).get("data", [])
        if avalon.ALIAS not in [entry.get("id") for entry in models]:
            raise RuntimeError("Avalon serves an unexpected model alias")
        yield BenchmarkEndpoint(
            "avalon",
            avalon.ALIAS,
            f"http://127.0.0.1:{port}/v1",
            "",
            int(ctx),
            metadata={
                "model_file": str(avalon.model_path()),
                "mtp_file": str(avalon.mtp_path()),
                "command": argv,
                "startup_seconds": time.perf_counter() - started,
                "reused": False,
            },
        )
    finally:
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        launch_util.sweep_escaped_children(port, process_started)
        process.wait(timeout=15)


def backend_endpoint(name: str, conf: llamacpp.LlamaConfig, output: RunPaths, config_path: Path | None = None):
    if name == "strata":
        return strata_endpoint(conf, output, config_path)
    if name == "avalon":
        return avalon_endpoint(conf, output)
    return llama_endpoint(conf, output)
