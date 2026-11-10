"""Bounded matched Strata profile screen: startup, prefill/cache, decode and expression checks."""

import argparse
import json
import re
import secrets
import statistics
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from scripts.benchmarks.coding_agents.shared.benchmark_requests import stream_chat
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.strata import strata_pi
from scripts.tests.shared import benchmark_config as benchmark_cfg
from scripts.tests.shared.backends import listening

PREFIX = "\n".join(
    f"def example_{i}(values):\n    return [value + {i} for value in values if value % 7 == {i % 7}]\n"
    for i in range(100)
)
QUALITY = (
    "Evaluate these Python expressions in order; return only one JSON array of results, no explanation: "
    "17*19; sum(range(10)); list(range(8))[::-2]; 'abc'[::-1]; "
    "len(set([1,1,2,3])); 7//3; 7%3; sorted([3,1,2])."
)
EXPECTED = [323, 45, [7, 5, 3, 1], "cba", 3, 2, 1, [1, 2, 3]]


def grade(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        values = json.loads(text)
    except json.JSONDecodeError:
        values = None
    passed = (
        sum(a == b for a, b in zip(values, EXPECTED, strict=True))
        if isinstance(values, list) and len(values) == len(EXPECTED)
        else 0
    )
    return {
        "passed": passed,
        "total": len(EXPECTED),
        "valid_json": isinstance(values, list),
        "exact": values == EXPECTED,
        "scope": "small expression smoke; not an agent/coding benchmark",
    }


class MemoryGuard:
    def __init__(self, process: subprocess.Popen[Any], deadline: float, minimum_gib: float, path: Path):
        self.process, self.deadline, self.minimum_gib, self.path = process, deadline, minimum_gib, path
        self.reason: str | None = None
        self.samples: list[dict[str, Any]] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_: object):
        self.stop.set()
        self.thread.join(timeout=10)

    def run(self) -> None:
        import psutil

        with self.path.open("w", encoding="utf-8") as stream:
            while not self.stop.is_set() and self.process.poll() is None:
                memory = psutil.virtual_memory()
                sample = {
                    "time": time.time(),
                    "available_gib": memory.available / 2**30,
                    "used_percent": memory.percent,
                }
                self.samples.append(sample)
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                if sample["available_gib"] < self.minimum_gib:
                    self.reason = f"Available RAM below {self.minimum_gib} GiB"
                elif time.monotonic() >= self.deadline:
                    self.reason = "Whole-run time budget reached"
                if self.reason:
                    launch_util.kill_process_tree(self.process.pid)
                    return
                self.stop.wait(0.5)


def request(connection: strata_pi.StrataConnection, prompt: str, tokens: int, deadline: float) -> dict[str, Any]:
    body = {
        "model": connection.config["model_name"],
        "messages": [
            {"role": "system", "content": "Follow the request precisely. Do not use tools."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "seed": 42,
        "max_tokens": tokens,
        "reasoning_effort": "none",
        "reasoning_budget_tokens": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return stream_chat(
        connection, body, timeout=max(1, min(90, deadline - time.monotonic())), extra={"output_limit": tokens}
    )


def run_arm(
    path: Path, output: RunPaths, args: argparse.Namespace, deadline: float, context: dict[str, Any]
) -> dict[str, Any]:
    source = strata_pi.saved_connections(path)[0]
    data: dict[str, Any] = {
        **source.config,
        "host": "127.0.0.1",
        "port": cfg.STRATA_SERVICE.port,
        "open_browser": False,
        "log": str(output.logs / "engine.log"),
        "reasoning_effort": "none",
        "reasoning_budget_tokens": 0,
    }
    for key in ("mcp_servers", "mcpServers", "mcp", "vision"):
        data.pop(key, None)
    data["args"] = [value for value in data["args"] if value != "--vision"]
    key = secrets.token_hex(32)
    data["api_key"] = key
    runtime = output.temp / "server.json"
    runtime.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    connection = strata_pi.StrataConnection(runtime, data, cfg.STRATA_SERVICE.port, key)
    result: dict[str, Any] = {"profile": str(path), "status": "running", "requests": []}
    (output.artifacts / "source-config.json").write_text(json.dumps(source.config, indent=2), encoding="utf-8")
    started = time.perf_counter()
    process = strata_pi.start_backend(connection, output.logs / "server.log")
    process_started = launch_util.process_start_time(process.pid)
    guard = MemoryGuard(process, deadline, args.minimum_ram_gib, output.logs / "ram.jsonl")
    try:
        with guard, BenchmarkVram(output, context) as vram:
            ready_until = min(deadline, time.monotonic() + args.startup_timeout)
            while time.monotonic() < ready_until:
                if process.poll() is not None:
                    raise RuntimeError(guard.reason or f"Server exited with {process.returncode}")
                if strata_pi.ready_model(connection):
                    break
                time.sleep(0.5)
            else:
                raise TimeoutError("Profile startup timed out")
            result["startup_seconds"] = time.perf_counter() - started
            from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle

            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{path}" if process.poll() is None else "")
            lifecycle.adopt_prepared(result["startup_seconds"])
            vram.watch_backend("strata", [process.pid])
            vram.stage = "warmup"
            lifecycle.warmup(
                lambda: result.update(warmup=request(connection, "Describe a red ball in one sentence.", 32, deadline))
            )
            vram.stage = "measured"
            for index in range(args.samples):
                prompt = PREFIX + f"\nSample {index}: explain Python lists versus tuples in at least 300 words."
                row, timing = lifecycle.measure(lambda: request(connection, prompt, args.tokens, deadline))
                row.update(timing)
                row["sample"] = index
                result["requests"].append(row)
                save_arm(output, result)
                print(f"  sample {index + 1}/{args.samples}: {row['seconds']:.2f}s", flush=True)
            quality = request(connection, QUALITY, 128, deadline)
            result["quality"] = {"request": quality, **grade(quality["content"])}
            result["status"] = "completed"
            result["benchmark"] = lifecycle.record()
    except Exception as error:
        result["status"], result["error"] = "failed", str(error)
    finally:
        result["memory"] = {
            "minimum_available_gib": min((row["available_gib"] for row in guard.samples), default=None),
            "abort_reason": guard.reason,
        }
        if guard.reason:
            result["status"], result["error"] = "failed", guard.reason
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        launch_util.sweep_escaped_children(connection.port, process_started)
        process.wait(timeout=15)
        result["total_seconds"] = time.perf_counter() - started
        save_arm(output, result)
    return result


def save_arm(output: RunPaths, result: dict[str, Any]) -> None:
    (output.artifacts / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="+", type=Path)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--tokens", type=int, default=128)
    parser.add_argument("--budget-seconds", type=int, default=270)
    parser.add_argument("--startup-timeout", type=int, default=110)
    parser.add_argument("--minimum-ram-gib", type=float, default=benchmark_cfg.MINIMUM_FREE_RAM_GIB)
    args = parser.parse_args()
    context = dict(require_native_execution("Strata profile benchmark"))
    if launch_util.llama_server_running():
        raise RuntimeError("An existing llama-server is running; it was not stopped")
    for port in {cfg.STRATA_SERVICE.port, *(strata_pi.saved_connections(path)[0].port for path in args.profiles)}:
        if listening(port):
            raise RuntimeError(f"Port {port} is occupied; no process was stopped")
    output = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {output.root}", flush=True)
    deadline = time.monotonic() + args.budget_seconds
    with report_run(
        output,
        "strata/strata_profiles",
        "low-context",
        "off",
        settings={
            "execution_context": context,
            "arguments": vars(args) | {"profiles": [str(p) for p in args.profiles]},
            "limits": [
                "Single ordered screening pair; not a ranking",
                "Filesystem/pagefile caches not reset",
                "Different profile settings bundled",
                "Expression smoke is not coding quality",
                "Fresh backends; common text-only requests, temperature 0, seed 42; 64K capacity, short actual input",
            ],
        },
    ) as report:
        for index, path in enumerate(args.profiles):
            if time.monotonic() >= deadline:
                report.status = "budget-exhausted"
                break
            arm = RunPaths(output.root / f"arm-{index}")
            arm.create()
            print(f"[PROFILE] {path.name}", flush=True)
            result = run_arm(path, arm, args, deadline, context)
            report.results.append(result)
            report.save(output)
            print(f"[RESULT] {result['status']}", flush=True)
        speeds = []
        for result in report.results:
            values = [(row.get("native_timings") or {}).get("predicted_per_second") for row in result["requests"]]
            speeds.append(
                statistics.median([v for v in values if v is not None]) if any(v is not None for v in values) else None
            )
        (output.artifacts / "summary.json").write_text(
            json.dumps(
                {
                    "native_decode_medians": speeds,
                    "profiles": [
                        {
                            k: item.get(k)
                            for k in ("profile", "status", "startup_seconds", "total_seconds", "memory", "error")
                        }
                        for item in report.results
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if any(item["status"] != "completed" for item in report.results):
            report.status = "incomplete"
    if report.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
