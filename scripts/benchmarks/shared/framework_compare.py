"""Compare the practice llama.cpp server, KoboldCpp and Lemonade on one GGUF.

Fast by default: one warmup plus two measured streaming requests per backend, each started
and stopped in turn so the GPU holds one model at a time.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import requests

from scripts.benchmarks.shared.paths import BenchmarkPaths
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp import kobold
from scripts.launchers.lemonade_server import lemonade
from scripts.launchers.llamacpp import llamacpp
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import get_gpu_memory_snapshot

WARMUP_PROMPT = "Say hello in one short sentence."
PROMPTS = (
    "Describe a quiet scouting mission near an enemy facility with a teammate.",
    "Explain why a small local model can still be useful for drafting code.",
)
BACKENDS = ("llamacpp", "koboldcpp", "lemonade")
DEFAULT_WEIGHTS = cfg.KOBOLDCPP_MODELS[cfg.KOBOLDCPP_SERVICE.model]


@dataclass(frozen=True)
class Served:
    """A running server, the model id its API expects, and the port it answers on."""

    base_url: str
    model: str
    port: int


@contextmanager
def _serve_koboldcpp(weights: Path) -> Iterator[Served]:
    port = cast(int, cfg.KOBOLDCPP_KCPPS_ARGS["port"])
    process, _config, _log = kobold.start_kobold()
    try:
        yield Served(f"http://127.0.0.1:{port}", weights.stem, port)
    finally:
        launch_util.kill_process_tree(process.pid, ports=port)


@contextmanager
def _serve_llamacpp(weights: Path) -> Iterator[Served]:
    config = llamacpp.LlamaConfig()
    config.model = weights
    process = llamacpp.launch(conf=config)
    try:
        yield Served(f"http://127.0.0.1:{config.port}", config.alias, config.port)
    finally:
        launch_util.kill_process_tree(process.pid, ports=config.port)


@contextmanager
def _serve_lemonade(weights: Path) -> Iterator[Served]:
    port = cfg.LEMONADE_SERVICE.port
    with lemonade.run_config(weights.parent, port):
        process, _log = lemonade.start(weights.parent, port)
        try:
            yield Served(f"http://127.0.0.1:{port}", weights.stem, port)
        finally:
            lemonade.stop(process, port)


def serve(name: str, weights: Path) -> AbstractContextManager[Served]:
    """Start one backend on the given file and stop it again."""
    handlers = {"llamacpp": _serve_llamacpp, "koboldcpp": _serve_koboldcpp, "lemonade": _serve_lemonade}
    return handlers[name](weights)


def stream_chat(served: Served, prompt: str, tokens: int) -> dict[str, Any]:
    """One streaming completion; the first content delta is the time to first token."""
    payload = {
        "model": served.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": tokens,
        "temperature": 0,
        "seed": 42,
        "stream": True,
    }
    started = time.perf_counter()
    first: float | None = None
    chunks = 0
    with requests.post(f"{served.base_url}/v1/chat/completions", json=payload, stream=True, timeout=300) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            delta = _delta_text(line)
            if delta is None:
                continue
            if first is None:
                first = time.perf_counter() - started
            chunks += 1
    seconds = time.perf_counter() - started
    return {
        "seconds": seconds,
        "first_token_seconds": first,
        "chunks": chunks,
        "chunks_per_second": chunks / seconds if seconds > 0 else None,
    }


def _delta_text(line: bytes) -> str | None:
    """The content of one server-sent delta, or None for keep-alive frames and the terminator."""
    if not line:
        return None
    text = line.decode("utf-8", errors="replace").removeprefix("data:").strip()
    if not text or text == "[DONE]":
        return None
    choices = json.loads(text).get("choices") or [{}]
    return (choices[0].get("delta") or {}).get("content") or None


def measure(name: str, weights: Path, tokens: int, requests_count: int) -> dict[str, Any]:
    """Serve one backend, drop a warmup, then record the measured requests."""
    load_started = time.perf_counter()
    with serve(name, weights) as served:
        load_seconds = time.perf_counter() - load_started
        before = get_gpu_memory_snapshot()
        stream_chat(served, WARMUP_PROMPT, tokens)
        rows = [stream_chat(served, prompt, tokens) for prompt in PROMPTS[:requests_count]]
        after = get_gpu_memory_snapshot()
    return {
        "backend": name,
        "model": weights.name,
        "load_seconds": load_seconds,
        "requests": rows,
        "vram_before": asdict(before) if before is not None else None,
        "vram_after": asdict(after) if after is not None else None,
    }


def summarize(results: list[dict[str, Any]]) -> list[str]:
    """One markdown row per backend; the mean of the measured requests decides the order."""
    lines = ["| backend | model | load s | TTFT s | chunks/s |", "| --- | --- | ---: | ---: | ---: |"]
    for result in results:
        rows = [row for row in result["requests"] if row["chunks"]]
        ttft = [row["first_token_seconds"] for row in rows if row["first_token_seconds"] is not None]
        rate = [row["chunks_per_second"] for row in rows if row["chunks_per_second"] is not None]
        lines.append(
            f"| {result['backend']} | {result['model']} | {result['load_seconds']:.1f} | "
            f"{_mean(ttft)} | {_mean(rate)} |"
        )
    return lines


def _mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else "n/a"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, help="GGUF served by every backend (default: the default chat model)")
    parser.add_argument(
        "--backend", choices=(*BACKENDS, "all"), default="all", help="backend to measure (default: all)"
    )
    parser.add_argument("--tokens", type=int, default=64, help="maximum reply tokens per request")
    parser.add_argument("--requests", type=int, default=2, help="measured requests per backend")
    args = parser.parse_args(argv)
    context = require_native_execution("Model server comparison")
    paths = BenchmarkPaths(source=__file__).new_run()
    paths.create()
    selected = BACKENDS if args.backend == "all" else (args.backend,)
    weights = args.weights or DEFAULT_WEIGHTS
    print(f"[INFO] weights: {weights}", flush=True)
    started = time.perf_counter()
    results = []
    for name in selected:
        print(f"[INFO] measuring {name}", flush=True)
        results.append(measure(name, weights, args.tokens, args.requests))
    report = {
        "name": "model server comparison",
        "category": "model-free server wiring; live native run",
        "status": "passed",
        "reasoning": "Same GGUF served by each backend, one warmup, mean of the measured requests.",
        "execution_context": context,
        "tokens": args.tokens,
        "total_seconds": time.perf_counter() - started,
        "results": results,
    }
    paths.write_report(report)
    table = "\n".join(summarize(results))
    (paths.artifacts / "summary.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
