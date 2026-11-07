"""Matched warmed decode traces at short or genuinely populated long context."""

import argparse
import csv
import hashlib
import json
import statistics
import time
import traceback
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import post_json, stop_server, wait_ready
from scripts.benchmarks.shared.paths import BenchmarkPaths, Outcome, RunPaths
from scripts.benchmarks.shared.vram import snapshot_dict
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor


def source_corpus() -> tuple[str, list[str]]:
    paths = sorted(
        path
        for directory in ("launchers", "download", "config", "tests/shared", "tests/cases/llamacpp")
        for path in (project_cfg.SCRIPTS_DIR / directory).rglob("*.py")
    )
    blocks, names = [], []
    size = 0
    for path in paths:
        if size + path.stat().st_size > 2 * 1024 * 1024:
            break
        name = path.relative_to(project_cfg.BASE_DIR).as_posix()
        blocks.append(f"\n# File: {name}\n{path.read_text(encoding='utf-8')}")
        names.append(name)
        size += path.stat().st_size
    return "\n".join(blocks), names


def token_windows(events: list[dict[str, Any]], width: int) -> list[dict[str, Any]]:
    if len(events) < 2:
        return []
    previous = events[0]
    windows = []
    for index, event in enumerate(events[1:], start=1):
        count = event["tokens"] - previous["tokens"]
        if count >= width or index == len(events) - 1:
            duration = event["seconds"] - previous["seconds"]
            if duration > 0 and count > 0:
                windows.append(
                    {
                        "start_token": previous["tokens"],
                        "end_token": event["tokens"],
                        "seconds": duration,
                        "tokens_per_second": count / duration,
                    }
                )
            previous = event
    return windows


def stream_request(
    base: str, prompt: list[int], args: argparse.Namespace, trace: Path, deadline: float
) -> dict[str, Any]:
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        raise TimeoutError("Benchmark time budget exhausted before request")
    payload = {
        "prompt": prompt,
        "n_predict": args.tokens,
        "temperature": 0,
        "seed": 42,
        "ignore_eos": True,
        "cache_prompt": True,
        "stream": True,
        "return_tokens": True,
        "timings_per_token": True,
        "return_progress": True,
        "sse_ping_interval": 1,
    }
    request = urllib.request.Request(
        base + "/completion", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    count, events, content = 0, [], []
    final = None
    with (
        trace.open("w", encoding="utf-8") as output,
        urllib.request.urlopen(request, timeout=min(args.request_timeout, remaining)) as response,
    ):
        for raw in response:
            elapsed = time.perf_counter() - started
            if time.perf_counter() > deadline or elapsed > args.request_timeout:
                raise TimeoutError("Benchmark or request time budget exhausted during request")
            if not raw.startswith(b"data:"):
                continue
            data = raw[5:].strip()
            if data == b"[DONE]":
                break
            item = json.loads(data)
            output.write(json.dumps({"seconds": elapsed, "response": item}) + "\n")
            if item.get("error"):
                raise RuntimeError(str(item["error"]))
            if item.get("stop"):
                final = item
                continue
            tokens = item.get("tokens") or []
            if tokens:
                count += len(tokens)
                events.append({"tokens": count, "seconds": elapsed})
            content.append(item.get("content", ""))
    if final is None:
        raise RuntimeError("Stream ended without final completion timings")
    expected = int(final["timings"]["predicted_n"])
    if count != expected or expected != args.tokens or final.get("truncated"):
        raise RuntimeError(
            f"Incomplete token trace: stream={count}, native={expected}, requested={args.tokens}, truncated={final.get('truncated')}"
        )
    windows = token_windows(events, args.window_tokens)
    (trace.with_suffix(".txt")).write_text("".join(content), encoding="utf-8")
    return {
        "request_seconds": time.perf_counter() - started,
        "first_token_seconds": events[0]["seconds"],
        "prompt_tokens": len(prompt),
        "prompt_sha256": hashlib.sha256(json.dumps(prompt).encode()).hexdigest(),
        "timings": final["timings"],
        "tokens_evaluated": final.get("tokens_evaluated"),
        "tokens_cached": final.get("tokens_cached"),
        "windows": windows,
        "trace": str(trace),
        "fraction_window_time_at_reference_rate": (
            sum(w["seconds"] for w in windows if w["tokens_per_second"] >= args.reference_rate)
            / sum(w["seconds"] for w in windows)
        )
        if windows
        else None,
    }


def parse_settings() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builds", nargs="+", choices=tuple(cfg.LLAMACPP_BUILDS), default=["vulkan", "rocm-lemonade"])
    parser.add_argument("--profile", default="swift15")
    parser.add_argument("--capacity", type=int, default=8192)
    parser.add_argument("--prompt-tokens", type=int, default=0)
    parser.add_argument("--tokens", type=int, default=512)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--window-tokens", type=int, default=64)
    parser.add_argument("--reference-rate", type=float, default=47.7)
    parser.add_argument("--request-timeout", type=float, default=240)
    parser.add_argument("--budget-sec", type=float, default=270)
    args = parser.parse_args()
    if min(args.tokens, args.runs, args.window_tokens, args.warmups) <= 0:
        parser.error("Positive output/sample/window sizes and at least one warmup are required")
    if args.prompt_tokens < 0 or args.prompt_tokens + args.tokens >= args.capacity:
        parser.error("Prompt plus output must fit configured context")
    return args


def prepare_prompts(
    base: str, labels: list[str], corpus: str, args: argparse.Namespace, run: RunPaths
) -> dict[str, list[int]]:
    source_tokens = post_json(base + "/tokenize", {"content": corpus}, 60)["tokens"] if corpus else []
    prompts = {}
    for index, label in enumerate(labels):
        suffix = (
            f"\nTask {index + 1}: Explain careful performance benchmarking in detail. "
            f"Use a distinct practical example involving {index + 7} workers. Answer:\n"
        )
        tail = post_json(base + "/tokenize", {"content": suffix}, 30)["tokens"]
        if args.prompt_tokens and len(source_tokens) < args.prompt_tokens - len(tail):
            raise RuntimeError("Varied source corpus is too short for the requested actual token depth")
        prompts[label] = source_tokens[: args.prompt_tokens - len(tail)] + tail if args.prompt_tokens else tail
    (run.artifacts / "prompt-tokens.json").write_text(json.dumps(prompts), encoding="utf-8")
    return prompts


def collect_requests(
    build: str,
    args: argparse.Namespace,
    run: RunPaths,
    monitor: GpuMemoryMonitor,
    prompts: dict[str, list[int]],
    result: dict[str, Any],
    deadline: float,
    lifecycle,
) -> None:
    for label, prompt in prompts.items():
        monitor.stage = label

        def operation():
            return stream_request(
                "http://127.0.0.1:9952", prompt, args, run.logs / f"tokens-{build}-{label}.jsonl", deadline
            )

        if label.startswith("warmup"):
            values = []
            lifecycle.warmup(lambda: values.append(operation()))
            row = values[0]
        else:
            row, timing = lifecycle.measure(operation)
            row.update(timing)
        result["warmups" if label.startswith("warmup") else "requests"].append({"label": label, **row})
        print(
            f"[RESULT] {build}/{label}: {row['timings']['predicted_per_second']:.2f} tok/s; input={row['prompt_tokens']}; TTFT={row['first_token_seconds']:.2f}s",
            flush=True,
        )
        if label == f"warmup-{args.warmups}":
            monitor.stage = "resident"
            result["resident"] = snapshot_dict(monitor.pid)


def benchmark_build(
    build: str,
    args: argparse.Namespace,
    run: RunPaths,
    prompts: dict[str, list[int]],
    corpus: str,
    evidence: dict[str, Any],
    deadline: float,
) -> None:
    config = LlamaConfig(args.profile, build_name=build, port=9952, ini_overrides={"fit": "off"})
    config.profile = replace(config.profile, extra_args={**config.profile.extra_args, "ctx-size": str(args.capacity)})
    log = run.logs / f"server-{build}.log"
    command = config.build_cmd(log)
    baseline = snapshot_dict()
    launch_started = time.perf_counter()
    process = launch_util.launch_process(
        command,
        title="llama.cpp context comparison",
        cwd=str(config.build_dir),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log),
        env=config.build_env,
    )
    monitor = GpuMemoryMonitor(process.pid, run.logs / f"vram-{build}.jsonl")
    monitor.stage = "startup"
    result: dict[str, Any] = {
        "command": command,
        "baseline": baseline,
        "model": str(config.model),
        "server_file": {
            "path": str(config.exe),
            "bytes": config.exe.stat().st_size,
            "mtime_ns": config.exe.stat().st_mtime_ns,
        },
        "warmups": [],
        "requests": [],
    }
    evidence["results"][build] = result
    try:
        with monitor:
            base = "http://127.0.0.1:9952"
            wait_ready(base, process, min(90, max(1, deadline - time.perf_counter())))
            result["startup_seconds"] = time.perf_counter() - launch_started
            from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle

            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{build}" if process.poll() is None else "")
            lifecycle.adopt_prepared(result["startup_seconds"])
            if not prompts:
                labels = [f"warmup-{i + 1}" for i in range(args.warmups)] + [
                    f"sample-{i + 1}" for i in range(args.runs)
                ]
                prompts.update(prepare_prompts(base, labels, corpus, args, run))
            collect_requests(build, args, run, monitor, prompts, result, deadline, lifecycle)
            result["benchmark"] = lifecycle.record()
    finally:
        stop_server(process)
        result["vram"] = monitor.summary()
    result["median_decode_tokens_per_second"] = statistics.median(
        r["timings"]["predicted_per_second"] for r in result["requests"]
    )


def write_outputs(run: RunPaths, evidence: dict[str, Any]) -> None:
    evidence["limitations"] = (
        "Short exploratory screen with fixed model/settings and varying task suffixes. "
        "Native per-request decode rates are separate from TTFT/prefill; window rates use receipt timestamps and may include buffering/speculative bursts. "
        "Shared prompt prefix may be cached after first prefill; inspect native cache_n/tokens_cached to determine actual reuse. Each request retains its recorded actual input depth. "
        "VRAM peaks are sampled lower bounds. Build revisions differ; this compares installed builds, not isolated backend code."
    )
    (run.artifacts / "results.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    columns = [
        "build",
        "request",
        "prompt_tokens",
        "native_decode_tokens_per_second",
        "ttft_seconds",
        "reference_rate_time_fraction",
        "vram_peak_process_mib",
    ]
    with (run.artifacts / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for build, result in evidence["results"].items():
            for row in result["requests"]:
                writer.writerow(
                    {
                        "build": build,
                        "request": row["label"],
                        "prompt_tokens": row["prompt_tokens"],
                        "native_decode_tokens_per_second": row["timings"]["predicted_per_second"],
                        "ttft_seconds": row["first_token_seconds"],
                        "reference_rate_time_fraction": row["fraction_window_time_at_reference_rate"],
                        "vram_peak_process_mib": result["vram"]["peak_process_used_mb"],
                    }
                )
    columns = ["build", "request", "start_token", "end_token", "seconds", "tokens_per_second"]
    with (run.artifacts / "windows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for build, result in evidence["results"].items():
            for row in result["requests"]:
                writer.writerows({"build": build, "request": row["label"], **window} for window in row["windows"])
    run.write_report(
        {
            "name": "llamacpp/benchmark_context_stream",
            "category": "llamacpp",
            "status": "incomplete" if evidence["errors"] else "completed",
            "total_seconds": evidence["total_seconds"],
            "reasoning": "not applicable (raw completion)",
            "limitations": evidence["limitations"],
        }
    )
    print(f"[OUTPUT] {run.root}", flush=True)


def main() -> None:
    args = parse_settings()
    context = require_native_execution("llama.cpp context benchmark")
    print(f"[OK] Execution context: {json.dumps(context)}", flush=True)
    if launch_util.llama_server_running() or launch_util.backend_running(9952):
        raise RuntimeError("An existing llama-server or occupied benchmark port requires session-safety approval")
    run = BenchmarkPaths(__file__).new_run(Outcome.INCONCLUSIVE)
    print(f"[OUTPUT] {run.root}", flush=True)
    started = time.perf_counter()
    evidence: dict[str, Any] = {"settings": vars(args), "execution_context": context, "results": {}, "errors": {}}
    prompts: dict[str, list[int]] = {}
    corpus, files = source_corpus() if args.prompt_tokens else ("", [])
    if corpus:
        (run.artifacts / "context-source.txt").write_text(corpus, encoding="utf-8")
    evidence["context_source_files"] = files
    try:
        for build in args.builds:
            benchmark_build(build, args, run, prompts, corpus, evidence, started + args.budget_sec)
    except Exception as error:
        evidence["errors"]["failure"] = f"{type(error).__name__}: {error}"
        evidence["errors"]["traceback"] = traceback.format_exc()
        print(f"[FAIL] {evidence['errors']['failure']}", flush=True)
    evidence["total_seconds"] = time.perf_counter() - started
    write_outputs(run, evidence)
    if evidence["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
