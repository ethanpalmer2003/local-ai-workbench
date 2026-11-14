"""Capture real client request options against a local stub, without inference."""

import argparse
import json
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from scripts.benchmarks.coding_agents.shared.benchmark_agents import CLIENTS, client_command
from scripts.benchmarks.coding_agents.shared.benchmark_backends import BenchmarkEndpoint
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import llamacpp
from scripts.shared.timing import timed


def capture_client(
    client: str,
    conf: llamacpp.LlamaConfig,
    endpoint: BenchmarkEndpoint,
    server: HTTPServer,
    bodies: list[dict[str, Any]],
    output: RunPaths,
) -> None:
    bodies.clear()
    command, env = client_command(client, conf, endpoint, output.temp / client / "agent")
    env["LLAMACPP_BASE_URL"] = f"http://127.0.0.1:{conf.port}/v1"
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.perf_counter()
    with (output.logs / f"{client}.log").open("wb") as log:
        process = subprocess.Popen(
            [*command, "Say OK. Do not use tools."],
            cwd=output.temp,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            while not bodies and process.poll() is None and time.perf_counter() - started < 30:
                server.handle_request()
        finally:
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
            process.wait(timeout=10)
    if not bodies:
        raise RuntimeError(f"No request from {client}; see {output.logs / f'{client}.log'}")
    body = bodies[0]
    (output.artifacts / f"{client}.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
    overrides = {
        key: body[key]
        for key in ("reasoning_effort", "thinking", "enable_thinking", "chat_template_kwargs")
        if key in body
    }
    print(f"{client}: {time.perf_counter() - started:.2f}s; reasoning overrides: {overrides}", flush=True)
    if overrides:
        raise AssertionError(f"{client} overrides server-default reasoning: {overrides}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("llamacpp", "strata"), default="llamacpp")
    parser.add_argument("--clients", nargs="+", choices=CLIENTS, default=list(CLIENTS))
    args = parser.parse_args()
    output = BenchmarkPaths(__file__).new_run()
    bodies: list[dict[str, Any]] = []
    conf = llamacpp.LlamaConfig()
    model = cfg.STRATA_SERVICE.model_name if args.backend == "strata" else conf.alias

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            body = json.dumps({"data": [{"id": model}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            bodies.append(body)
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Request captured; no model is running"}}')

    with report_run(output, "shared/harness_requests", "model-free"), HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 0.5
        conf.port = server.server_port
        endpoint = BenchmarkEndpoint(args.backend, model, f"http://127.0.0.1:{server.server_port}/v1", "noop")
        for client in args.clients:
            capture_client(client, conf, endpoint, server, bodies, output)
    print(f"[OUTPUT] {output.root}")


if __name__ == "__main__":
    with timed("shared/harness_requests"):
        main()
