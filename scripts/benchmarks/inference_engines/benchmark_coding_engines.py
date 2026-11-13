"""Coding-engine benchmark: prefill, decode and time to first token on one prompt set.

- One task corpus and one request contract for every engine, so a row from one
  engine means the same thing as a row from another
- Each task is sent once cold (a unique nonce defeats the prompt cache, which is
  the real prefill measurement), then once unmeasured to warm the prefix and the
  draft model, then `--samples` times warm (cache reuse)
- Decode and TTFT report the median of the per-task medians with the observed
  range; pooling the raw samples mixed the ramp into the rate, which is what made
  one task read 31 and 67 tok/s in the same run
- Prefill, decode and TTFT come from the server's own `timings` block through
  the shared `stream_metrics`, so no wall-clock proxy is mixed in
- Engines: `--engine llamacpp` starts a configured profile and build locally;
  `--engine endpoint` dials any OpenAI-compatible server (Strata, Avalon,
  Lemonade, KoboldCpp, vLLM) that is already running
- A run stops only the server it started; an endpoint run starts nothing
"""

from __future__ import annotations

import argparse
import contextlib
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.benchmarks.coding_agents.shared.benchmark_requests import stream_chat, stream_metrics
from scripts.benchmarks.coding_agents.strata_profiles import PREFIX
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.timing import timed
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig
from scripts.launchers.llamacpp.llamacpp_profiles import LLAMACPP_BENCHMARK_PROFILES, LLAMACPP_PROFILES
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.services.process import http_ready

CODING_TASKS: dict[str, str] = {
    "implement": "Add a pure function `chunk(text, limit)` that splits on whitespace without exceeding `limit`.",
    "debug": "This loop skips the last element:\n\nfor i in range(len(items) - 1):\n    use(items[i])\n\nExplain the fix.",
    "tests": "Write three unittest cases for a function that parses `key=value` lines and ignores `#` comments.",
    "refactor": (
        "Rewrite this as a small class with one responsibility:\n\n"
        "def load(path):\n    ...\n\ndef save(path, data):\n    ..."
    ),
}

SYSTEM = "You are a concise coding assistant. Answer with code first, then one short paragraph."
NONCE = "\n\n[benchmark screen, request {index}]"
TIMING_FIELDS = ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms", "draft_n", "draft_n_accepted")


@dataclass(frozen=True)
class Connection:
    base_url: str
    api_key: str


@dataclass
class EngineSession:
    """What a run owns: an endpoint, and a process only when it started one."""

    name: str
    connection: Connection
    model: str
    features: str = ""
    process: subprocess.Popen[Any] | None = None
    startup_seconds: float | None = None
    log_file: Path | None = None

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            launch_util.kill_process_tree(self.process.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.process.wait(timeout=15)


def llamacpp_session(args: argparse.Namespace, output: RunPaths) -> EngineSession:
    profiles = {**LLAMACPP_PROFILES, **LLAMACPP_BENCHMARK_PROFILES}
    if args.profile not in profiles:
        raise ValueError(f"Unknown profile {args.profile}; choose from {', '.join(sorted(profiles))}")
    config = LlamaConfig(args.profile, build_name=args.build, profiles=profiles)
    log_file = output.logs / "llama-server.log"
    process = launch_util.launch_process(
        config.build_cmd(log_file),
        "Coding engine benchmark",
        cwd=str(config.build_dir),
        kill_ports=config.port,
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log_file),
        env=config.build_env,
    )
    return EngineSession(
        name="llamacpp",
        connection=Connection(f"http://127.0.0.1:{cfg.LLAMACPP_SERVICE.port}/v1", ""),
        model=Path(profiles[args.profile].model).name,
        features=f"build {args.build or cfg.LLAMACPP_ACTIVE_BUILD}; profile {args.profile}",
        process=process,
        log_file=log_file,
    )


def endpoint_session(args: argparse.Namespace) -> EngineSession:
    if not args.endpoint:
        raise ValueError("--endpoint URL is required for --engine endpoint")
    base = args.endpoint.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return EngineSession(
        name="endpoint",
        connection=Connection(base, args.api_key),
        model=args.model,
        features=f"existing OpenAI-compatible server at {args.endpoint}",
    )


def wait_started(session: EngineSession, timeout: float) -> float:
    if session.process is None:
        return 0.0
    started = time.perf_counter()
    parts = urlsplit(session.connection.base_url)
    health = f"{parts.scheme}://{parts.netloc}/health"
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if session.process.poll() is not None:
            raise RuntimeError(f"{session.name} exited with {session.process.returncode}")
        if http_ready(health, timeout=2):
            return time.perf_counter() - started
        time.sleep(0.5)
    raise TimeoutError(f"{session.name} did not become ready within {timeout:g} seconds")


def conversation(task: str, context: str, *, suffix: str = "") -> list[dict[str, str]]:
    content = f"{context}\n\n{task}" if context else task
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content + suffix}]


def request_body(model: str, messages: list[dict[str, str]], tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "max_tokens": tokens,
        "temperature": 0,
        "seed": 42,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def task_rows(session: EngineSession, args: argparse.Namespace, context: str) -> dict[str, Any]:
    model = session.model or "default"
    stream_chat(
        session.connection, request_body(model, conversation("Reply with the word ready.", ""), 8), timeout=args.timeout
    )
    cold: dict[str, dict[str, Any]] = {}
    warm: dict[str, list[dict[str, Any]]] = {}
    for index, (label, task) in enumerate(CODING_TASKS.items()):
        prompt = conversation(task, context)
        cold[label] = stream_chat(
            session.connection,
            request_body(model, conversation(task, context, suffix=NONCE.format(index=index)), 8),
            timeout=args.timeout,
        )
        cold_rate = (cold[label].get("native_timings") or {}).get("prompt_per_second")
        print(f"  {label}: cold prefill {cold_rate} tok/s", flush=True)
        # - one unmeasured request warms the shared prefix and the draft model; without it the
        #   first measured sample carries the ramp and pulls the reported rate down
        stream_chat(session.connection, request_body(model, prompt, args.tokens), timeout=args.timeout)
        warm[label] = []
        for sample in range(args.samples):
            warm[label].append(
                stream_chat(session.connection, request_body(model, prompt, args.tokens), timeout=args.timeout)
            )
            metrics = stream_metrics(warm[label])
            print(
                f"  {label} sample {sample + 1}/{args.samples}: "
                f"prefill {metrics['prefill_tokens_per_second']} tok/s, "
                f"decode {metrics['decode_tokens_per_second']} tok/s, "
                f"TTFT {metrics['ttft_seconds']} s",
                flush=True,
            )
    return {"cold": cold, "warm": warm}


def sample_spread(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Median and range of one task's samples; pooling the totals hides how far apart they are."""
    rates = [stream_metrics([row]) for row in samples]
    decode = [rate["decode_tokens_per_second"] for rate in rates if rate["decode_tokens_per_second"] is not None]
    ttft = [rate["ttft_seconds"] for rate in rates if rate["ttft_seconds"] is not None]
    if not decode:
        return {"decode_median": None, "decode_min": None, "decode_max": None, "ttft_median": None}
    return {
        "decode_median": round(statistics.median(decode), 1),
        "decode_min": round(min(decode), 1),
        "decode_max": round(max(decode), 1),
        "ttft_median": round(statistics.median(ttft), 3) if ttft else None,
    }


def summarize(rows: dict[str, Any]) -> dict[str, Any]:
    cold = stream_metrics(list(rows["cold"].values()))
    warm = stream_metrics([row for samples in rows["warm"].values() for row in samples])
    per_task = {label: sample_spread(samples) for label, samples in rows["warm"].items()}
    medians = [task["decode_median"] for task in per_task.values() if task["decode_median"] is not None]
    ttfts = [task["ttft_median"] for task in per_task.values() if task["ttft_median"] is not None]
    return {
        # - only the cold request fills the whole prompt; a warm sample prefills the cache miss
        #   alone, so a warm prefill rate would report a four-token latency as throughput
        "cold_prefill_tokens_per_second": cold["prefill_tokens_per_second"],
        "cold_prefill_seconds": cold["prefill_seconds"],
        "decode_tokens_per_second": round(statistics.median(medians), 1) if medians else None,
        "decode_range": (
            (
                min(task["decode_min"] for task in per_task.values()),
                max(task["decode_max"] for task in per_task.values()),
            )
            if medians
            else None
        ),
        "ttft_seconds": round(statistics.median(ttfts), 3) if ttfts else None,
        "draft_acceptance": warm["draft_acceptance"],
        "prompt_tokens": statistics.median(
            (row.get("usage") or {}).get("prompt_tokens", 0) for row in rows["cold"].values()
        ),
        "tasks": len(rows["cold"]),
        "samples": sum(len(samples) for samples in rows["warm"].values()),
        "per_task": per_task,
    }


def request_record(row: dict[str, Any]) -> dict[str, Any]:
    """The fields a reader needs; a raw stream record is much larger."""
    timings = row.get("native_timings") or {}
    return {
        "seconds": row.get("seconds"),
        "ttft_seconds": row.get("first_token_seconds"),
        "usage": row.get("usage") or {},
        "native_timings": {key: timings.get(key) for key in TIMING_FIELDS},
        "finished": row.get("finished"),
    }


def run_engine(args: argparse.Namespace, output: RunPaths, context: str) -> dict[str, Any]:
    session = llamacpp_session(args, output) if args.engine == "llamacpp" else endpoint_session(args)
    try:
        if session.process is not None:
            session.startup_seconds = wait_started(session, args.startup_timeout)
        rows = task_rows(session, args, context)
        result = summarize(rows)
        result.update(
            {
                "engine": session.name,
                "model": session.model,
                "features": session.features,
                "startup_seconds": session.startup_seconds,
                "cold_requests": {label: request_record(row) for label, row in rows["cold"].items()},
                "warm_requests": {
                    label: [request_record(row) for row in samples] for label, samples in rows["warm"].items()
                },
            }
        )
        return result
    finally:
        session.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Coding-engine prefill, decode and TTFT benchmark")
    parser.add_argument("--engine", choices=("llamacpp", "endpoint"), default="llamacpp")
    parser.add_argument("--profile", default="swift15", help="llama.cpp profile (--engine llamacpp)")
    parser.add_argument("--build", default=None, help="llama.cpp build (default: the active build)")
    parser.add_argument("--endpoint", default=None, help="OpenAI-compatible base URL (--engine endpoint)")
    parser.add_argument("--api-key", default="", help="Bearer token for --endpoint")
    parser.add_argument("--model", default="", help="Model name a server requires in the request body")
    parser.add_argument("--tokens", type=int, default=128, help="Tokens generated per measured request")
    parser.add_argument("--samples", type=int, default=3, help="Warm measured requests per task")
    parser.add_argument("--context", choices=("prefix", "none"), default="prefix", help="Code context before each task")
    parser.add_argument("--startup-timeout", type=float, default=180)
    parser.add_argument("--timeout", type=float, default=600, help="Per-request timeout in seconds")
    args = parser.parse_args()

    context_info = require_native_execution("coding-engine benchmark") if args.engine == "llamacpp" else {}
    if args.engine == "llamacpp" and launch_util.llama_server_running():
        raise RuntimeError("Existing llama.cpp session retained; close it before a local run")
    output = BenchmarkPaths(__file__).new_run()
    context = PREFIX if args.context == "prefix" else ""
    with report_run(
        output,
        "llm/benchmark_coding_engines",
        "llm-inference",
        settings={
            "execution_context": context_info,
            "arguments": vars(args),
            "contract": "4 coding tasks, temperature 0, seed 42, server-native timings",
            "context": "strata_profiles PREFIX (100 Python functions)" if context else "none",
        },
    ) as report:
        started = time.perf_counter()
        result = run_engine(args, output, context)
        result["wall_seconds"] = time.perf_counter() - started
        report.results.append(result)
        report.save(output)
        lines = [
            f"engine: {result['engine']}  model: {result['model']}",
            f"features: {result['features']}",
            f"startup: {result['startup_seconds']} s",
            f"cold prefill: {result['cold_prefill_tokens_per_second']} tok/s "
            f"({result['cold_prefill_seconds']} s for {result['prompt_tokens']} prompt tokens)",
            f"decode: {result['decode_tokens_per_second']} tok/s (median of task medians)",
            f"decode range: {result['decode_range']}",
            f"TTFT: {result['ttft_seconds']} s",
            f"draft acceptance: {result['draft_acceptance']}",
        ]
        lines += [
            f"  {label}: decode {task['decode_median']} tok/s ({task['decode_min']}-{task['decode_max']}), "
            f"TTFT {task['ttft_median']} s"
            for label, task in result["per_task"].items()
        ]
        summary = output.artifacts / "summary.txt"
        summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        print(f"[OK] summary: {summary}")


if __name__ == "__main__":
    with timed("llm/benchmark_coding_engines"):
        main()
