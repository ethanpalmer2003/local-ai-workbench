"""Quick, meaningful tokens-per-second benchmark for configured llama.cpp profiles.

- Run from C:/AI: `python -m scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles`
- Per profile: launch server once, send untimed warmup request, then time
  several *decode-only* requests per test prompt
- Uses llama.cpp's own `timings.predicted_per_second` from the native
  /completion endpoint
  - Prompt processing, network latency, server startup never leak into numbers
- Multiple repeats matter for speculative decoding (MTP)
  - Throughput depends on how often drafts get accepted, which varies with
    the sampled text
  - A single request is not a reliable signal for those profiles
- `ignore_eos` forces every timed request to generate exactly `--max-tokens`
  - Run lengths (and accept-rate exposure) comparable across profiles
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import BENCHMARK_REASONING_EFFORT, report_run
from scripts.benchmarks.shared.timing import timed
from scripts.benchmarks.shared.vram import snapshot_dict
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig
from scripts.launchers.llamacpp.llamacpp_profiles import LLAMACPP_BENCHMARK_PROFILES, LLAMACPP_PROFILES
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor

# - Two short, fixed prompts covering the two workloads these profiles
#   actually get used for (general chat/reasoning vs. coding)
# - Kept short on purpose: we only care about decode speed, not prompt
#   processing speed, and a short prompt keeps the whole sweep quick
output = RunPaths(BenchmarkPaths(__file__).output)

DEFAULT_PROMPTS: dict[str, str] = {
    "prose": "Write a concise paragraph explaining why careful benchmarking matters.",
    "code": (
        "Write a Python function `is_prime(n: int) -> bool` with a docstring "
        "and a couple of inline comments explaining the approach."
    ),
}

# - Deliberately tricky little questions that tempt a reasoning model into
#   long thinking traces for a one-line answer
OVERTHINK_PROMPTS: dict[str, str] = {
    "bait": "Which is larger, 9.11 or 9.9? Answer with just the number.",
    # - Simon Willison's Qwen3.8 xhigh overthinking baits: trivial generation
    #   tasks that spiral into huge thinking traces at high effort
    "pelican-svg": "Generate an SVG of a pelican riding a bicycle.",
    "circle-svg": "Draw an SVG of a circle.",
}

# - Filler for --ctx-fill: prepended to every prompt so decode is measured at a
#   given context depth. ~4 chars/token is a rough English approximation; the
#   server reports the exact depth as prompt_n, which the summary prints.
FILLER_SENTENCE = (
    "The quick brown fox jumps over the lazy dog while the benchmark measures decode throughput at depth. "
)


def build_filler(target_tokens: int) -> str:
    if target_tokens <= 0:
        return ""
    repeats = max(1, (target_tokens * 4) // len(FILLER_SENTENCE))
    return FILLER_SENTENCE * repeats


@dataclass
class Sample:
    tokens: int
    seconds: float
    tokens_per_second: float
    prompt_tokens: int = 0  # - actual context depth the server processed
    prompt_seconds: float = 0.0


def post_json(url: str, payload: Mapping[str, object], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))


def wait_ready(base_url: str, process: subprocess.Popen[bytes], timeout: float) -> None:
    from scripts.launchers.shared.services.process import http_ready
    from scripts.launchers.shared.services.process import wait_ready as wait_process

    wait_process(
        process,
        lambda: http_ready(base_url + "/health", timeout=2),
        timeout,
        label=f"llama-server at {base_url}",
        interval=1,
    )


def stop_server(process: subprocess.Popen[bytes]) -> None:
    from scripts.launchers.shared.services.process import stop_owned

    stop_owned(process, timeout=10, graceful=True)


def completion_request(base_url: str, prompt: str, n_predict: int, timeout: float, cache_prompt: bool = True) -> Sample:
    """Send one /completion request and time decode only, via server-reported timings.

    - Prefers timings.predicted_n / predicted_ms from the response
    - cache_prompt=False forces a fresh prompt processing, so timings.prompt_n
      reports the true context depth (used by --ctx-fill)
    """
    payload = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0.2,
        "stream": False,
        "ignore_eos": True,  # - force fixed-length generation so runs are comparable
        "cache_prompt": cache_prompt,
    }
    result = post_json(f"{base_url}/completion", payload, timeout=timeout)
    timings = result["timings"]
    tokens = int(timings["predicted_n"])
    seconds = float(timings["predicted_ms"]) / 1000.0
    if seconds <= 0:
        raise RuntimeError("Server reported zero decode time")
    return Sample(
        tokens,
        seconds,
        tokens / seconds,
        int(timings.get("prompt_n") or 0),
        float(timings.get("prompt_ms") or 0) / 1000.0,
    )


def run_profile(
    profile_name: str,
    prompts: dict[str, str],
    max_tokens: int,
    warmup_tokens: int,
    repeats: int,
    startup_timeout: float,
    request_timeout: float,
    build_name: str | None = None,
    ctx_fill: int = 0,
) -> tuple[dict[str, list[Sample]], dict[str, Any]]:
    context = require_native_execution("llama.cpp benchmark")
    from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle

    if launch_util.llama_server_running() or launch_util.port_listening(cfg.LLAMACPP_SERVICE.port):
        raise RuntimeError("Existing llama.cpp session/port retained; use a free test session")
    # - benchmark profiles live in their own dict (not in the launcher's
    #   LLAMACPP_PROFILES); merge so both are addressable by name
    all_profiles = {**LLAMACPP_PROFILES, **LLAMACPP_BENCHMARK_PROFILES}
    config = LlamaConfig(
        profile_name,
        build_name=build_name,
        profiles=all_profiles,
        ini_overrides={"reasoning-effort": BENCHMARK_REASONING_EFFORT},
    )
    log_file = output.logs / f"llama-benchmark-{build_name or 'active'}-{profile_name}.log"
    command = config.build_cmd(log_file)
    base_url = f"http://127.0.0.1:{cfg.LLAMACPP_SERVICE.port}"
    baseline = snapshot_dict()
    startup_started = time.perf_counter()
    process = launch_util.launch_process(
        command,
        "Model benchmark",
        cwd=str(config.build_dir),
        kill_ports=config.port,
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log_file),
        env=config.build_env,
    )

    results: dict[str, list[Sample]] = {}
    monitor = GpuMemoryMonitor(process.pid, output.logs / f"vram-{build_name or 'active'}-{profile_name}.jsonl")
    monitor.stage = "startup"
    warmup_seconds = {}
    resident = {}
    try:
        with monitor:
            wait_ready(base_url, process, startup_timeout)
            startup_seconds = time.perf_counter() - startup_started
            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{profile_name}" if process.poll() is None else "")
            lifecycle.adopt_prepared(startup_seconds)
            filler = build_filler(ctx_fill)
            use_cache = not ctx_fill
            for label, prompt in prompts.items():
                full_prompt = filler + prompt
                monitor.stage = f"warmup-{label}"
                warmup_started = time.perf_counter()
                lifecycle.warmup(
                    lambda: completion_request(base_url, full_prompt, warmup_tokens, request_timeout, use_cache)
                )
                warmup_seconds[label] = time.perf_counter() - warmup_started
                monitor.stage = f"resident-{label}"
                resident[label] = snapshot_dict(process.pid)
                results[label] = []
                for index in range(repeats):
                    monitor.stage = f"request-{label}-{index + 1}"
                    sample, _ = lifecycle.measure(
                        lambda: completion_request(base_url, full_prompt, max_tokens, request_timeout, use_cache)
                    )
                    results[label].append(sample)
    finally:
        stop_server(process)

    metrics = {
        "benchmark": lifecycle.record(),
        **monitor.summary(),
        "baseline": baseline,
        "resident": resident,
        "startup_seconds": startup_seconds,
        "warmup_seconds": warmup_seconds,
        "command": command,
        "trace": str(monitor.log_path),
        "execution_context": context,
        "request_samples": {name: [asdict(sample) for sample in samples] for name, samples in results.items()},
        "limitations": "Sampled dedicated-memory counters; peaks may be missed. Per-process allocations can exceed adapter physical usage. Counter polling may affect CPU load.",
    }
    (output.artifacts / f"metrics-{build_name or 'active'}-{profile_name}.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    return results, metrics


def profile_meta(profile_name: str, build_name: str | None) -> dict[str, str]:
    """Resolve a profile's model/ini/params for the CSV record."""
    all_profiles = {**LLAMACPP_PROFILES, **LLAMACPP_BENCHMARK_PROFILES}
    profile = all_profiles[profile_name]
    params = "; ".join(f"{k}={v}" for k, v in sorted(profile.extra_args.items()))
    return {
        "build": build_name or cfg.LLAMACPP_ACTIVE_BUILD,
        "profile": profile_name,
        "model": profile.model,
        "ini": profile.ini,
        "params": params,
    }


def summarize(samples: list[Sample]) -> str:
    values = [s.tokens_per_second for s in samples]
    mean = statistics.mean(values)
    if len(values) > 1:
        spread = statistics.stdev(values)
        return f"{mean:.1f} +/- {spread:.1f}"
    return f"{mean:.1f}"


def overthink_profile(
    profile_name: str,
    prompts: dict[str, str],
    startup_timeout: float,
    request_timeout: float,
    build_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    """One chat request per prompt; reports how much of the generation went
    to thinking vs the visible answer.

    - Uses /v1/chat/completions so the template actually renders (reasoning
      effort / thinking defaults apply)
    - reasoning-format=auto (set in the ini) splits thoughts into
      message.reasoning_content; char counts stand in for token counts
    - No max_tokens cap - runaways get unlimited room
    - Single request, no repeats, no ignore_eos - this is a behavior probe,
      not a speed benchmark
    """
    all_profiles = {**LLAMACPP_PROFILES, **LLAMACPP_BENCHMARK_PROFILES}
    config = LlamaConfig(
        profile_name,
        build_name=build_name,
        profiles=all_profiles,
        ini_overrides={"reasoning-effort": BENCHMARK_REASONING_EFFORT},
    )
    log_file = output.logs / f"llama-overthink-{build_name or 'active'}-{profile_name}.log"
    command = config.build_cmd(log_file)
    base_url = f"http://127.0.0.1:{cfg.LLAMACPP_SERVICE.port}"
    process = launch_util.launch_process(
        command,
        "Model behavior probe",
        cwd=str(config.build_dir),
        kill_ports=config.port,
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log_file),
    )

    results: dict[str, dict[str, Any]] = {}
    try:
        wait_ready(base_url, process, startup_timeout)

        for label, prompt in prompts.items():
            wall_start = time.perf_counter()
            response = post_json(
                f"{base_url}/v1/chat/completions",
                {"messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "stream": False},
                timeout=request_timeout,
            )
            wall_elapsed = time.perf_counter() - wall_start

            message = (response.get("choices") or [{}])[0].get("message", {})
            thinking = str(message.get("reasoning_content") or "")
            answer = str(message.get("content") or "")
            timings = response.get("timings") or {}
            tokens = int(timings.get("predicted_n") or response.get("usage", {}).get("completion_tokens") or 0)
            seconds = float(timings.get("predicted_ms") or 0) / 1000.0 or wall_elapsed
            results[label] = {
                "tokens": tokens,
                "tokens_per_second": tokens / seconds if seconds > 0 else 0.0,
                "wall_seconds": wall_elapsed,
                "think_chars": len(thinking),
                "answer_chars": len(answer),
                "answer": answer.strip(),
            }

            results[label]["thinking"] = thinking
            results[label]["prompt"] = prompt

        # Write all transcripts as a single JSON file
        transcript_path = (
            output.artifacts / "overthink" / f"{build_name or cfg.LLAMACPP_ACTIVE_BUILD}-{profile_name}.json"
        )
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        stop_server(process)

    return results


def overthink_line(run_label: str, label: str, row: dict[str, Any]) -> str:
    total_chars = row["think_chars"] + row["answer_chars"]
    share = f"{row['think_chars'] / total_chars:.0%}" if total_chars else "-"
    # - ~8k thinking tokens at ~3 chars/token
    runaway = " RUNAWAY" if row["think_chars"] >= 24000 else ""
    return (
        f"{run_label}\t{label}\t{row['tokens']}{runaway}\t{row['tokens_per_second']:.1f}\t"
        f"{row['wall_seconds']:.1f}\t{row['think_chars']}\t{row['answer_chars']}\t{share}\t{row['answer'][:60]}"
    )


def run_overthink(
    args: argparse.Namespace, builds: list[str | None], prompts: dict[str, str], summary_lines: list[str]
) -> bool:
    summary_lines.append("build/profile\tprompt\ttokens\ttok/s\twall_s\tthink_chars\tanswer_chars\tthink_share\tanswer")
    print(summary_lines[-1])
    failed = False
    for build_name in builds:
        for profile_name in args.profiles:
            run_label = f"{build_name or cfg.LLAMACPP_ACTIVE_BUILD}/{profile_name}"
            print(f"{run_label}\t-\tstarting", flush=True)
            try:
                results = overthink_profile(
                    profile_name, prompts, args.startup_timeout, args.request_timeout, build_name
                )
                for label, row in results.items():
                    line = overthink_line(run_label, label, row)
                    summary_lines.append(line)
                    print(line, flush=True)
            except Exception as error:
                failed = True
                line = f"{run_label}\tERROR\t{error}"
                summary_lines.append(line)
                print(line, flush=True)
    return failed


def decode_profile(
    build_name: str | None,
    run_label: str,
    profile_name: str,
    results: dict[str, list[Sample]],
    memory: dict[str, Any],
    summary_lines: list[str],
) -> list[dict[str, str]]:
    meta = profile_meta(profile_name, build_name)
    resident_values = [
        s["process_used_mb"] for s in memory["resident"].values() if s and s["process_used_mb"] is not None
    ]
    meta.update(
        {
            "vram_resident_process_mib": str(max(resident_values)) if resident_values else "",
            "vram_peak_process_mib": str(memory["peak_process_used_mb"])
            if memory["peak_process_used_mb"] is not None
            else "",
            "vram_peak_adapter_mib": str(memory["peak_total_used_mb"])
            if memory["peak_total_used_mb"] is not None
            else "",
        }
    )
    csv_rows: list[dict[str, str]] = []
    all_samples: list[Sample] = []
    for label, samples in results.items():
        all_samples.extend(samples)
        avg_seconds = statistics.mean(s.seconds for s in samples)
        line = (
            f"{run_label}\t{label}\t{samples[0].tokens}\t"
            f"{samples[0].prompt_tokens}\t{avg_seconds:.1f}\t{summarize(samples)}"
        )
        summary_lines.append(line)
        print(line, flush=True)
        csv_rows.append(
            {
                **meta,
                "prompt": label,
                "tokens": str(samples[0].tokens),
                "ctx_depth": str(samples[0].prompt_tokens),
                "avg_s": f"{avg_seconds:.1f}",
                "tok_s": summarize(samples),
            }
        )
    if len(results) > 1:
        avg_seconds = statistics.mean(s.seconds for s in all_samples)
        line = (
            f"{run_label}\toverall\t{all_samples[0].tokens}\t"
            f"{all_samples[0].prompt_tokens}\t{avg_seconds:.1f}\t{summarize(all_samples)}"
        )
        summary_lines.append(line)
        print(line, flush=True)
        csv_rows.append(
            {
                **meta,
                "prompt": "overall",
                "tokens": str(all_samples[0].tokens),
                "ctx_depth": str(all_samples[0].prompt_tokens),
                "avg_s": f"{avg_seconds:.1f}",
                "tok_s": summarize(all_samples),
            }
        )
    return csv_rows


def run_decode(
    args: argparse.Namespace, builds: list[str | None], prompts: dict[str, str], summary_lines: list[str]
) -> tuple[bool, list[dict[str, str]]]:
    summary_lines.append("build/profile\tprompt\ttokens\tctx_depth\tavg_s\ttok/s")
    print(summary_lines[-1])
    failed = False
    csv_rows: list[dict[str, str]] = []
    for build_name in builds:
        for profile_name in args.profiles:
            run_label = f"{build_name or cfg.LLAMACPP_ACTIVE_BUILD}/{profile_name}"
            print(f"{run_label}\t-\tstarting", flush=True)
            try:
                results, memory = run_profile(
                    profile_name,
                    prompts,
                    args.max_tokens,
                    args.warmup_tokens,
                    args.repeats,
                    args.startup_timeout,
                    args.request_timeout,
                    build_name,
                    args.ctx_fill,
                )
                csv_rows += decode_profile(build_name, run_label, profile_name, results, memory, summary_lines)
            except Exception as error:
                failed = True
                line = f"{run_label}\tERROR\t{error}"
                summary_lines.append(line)
                print(line, flush=True)
    return failed, csv_rows


def write_summary(output: RunPaths, summary_lines: list[str], name: str) -> Path:
    summary_lines.append("")
    summary_lines.append(f"Benchmark finished: {datetime.now().isoformat(timespec='seconds')}")
    summary_file = output.artifacts / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.txt"
    summary_file.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"Summary written to: {summary_file}")
    return summary_file


def write_csv(output: RunPaths, csv_rows: list[dict[str, str]]) -> None:
    csv_file = output.artifacts / f"llama-benchmark-csv-{datetime.now():%Y%m%d-%H%M%S}.csv"
    fieldnames = [
        "timestamp",
        "build",
        "profile",
        "model",
        "ini",
        "params",
        "prompt",
        "tokens",
        "ctx_depth",
        "avg_s",
        "tok_s",
        "vram_resident_process_mib",
        "vram_peak_process_mib",
        "vram_peak_adapter_mib",
    ]
    stamp = datetime.now().isoformat(timespec="seconds")
    with csv_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow({**row, "timestamp": stamp})
    print(f"CSV written to: {csv_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark configured llama.cpp profiles")
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=sorted({**LLAMACPP_PROFILES, **LLAMACPP_BENCHMARK_PROFILES}),
        default=["swift15", "swift15-mtp-notemplate"],
        help="Profiles to benchmark (default: Swift 1.5 template A/B pair).",
    )
    parser.add_argument(
        "--builds",
        nargs="+",
        choices=sorted(cfg.LLAMACPP_BUILDS),
        default=None,
        help="llama.cpp build(s) to benchmark (default: the active build). "
        "Runs the cross product with --profiles, so one run can A/B builds.",
    )
    parser.add_argument(
        "--prompt-set",
        nargs="+",
        choices=sorted(DEFAULT_PROMPTS),
        default=sorted(DEFAULT_PROMPTS),
        help="Which built-in prompts to test (default: all).",
    )
    parser.add_argument("--max-tokens", type=int, default=128, help="Tokens generated per timed request.")
    parser.add_argument("--warmup-tokens", type=int, default=32, help="Tokens generated by the untimed warmup request.")
    parser.add_argument("--repeats", type=int, default=3, help="Timed requests per prompt (more = less noisy, slower).")
    parser.add_argument(
        "--ctx-fill",
        type=int,
        default=0,
        help="Approximate tokens of filler prepended to every prompt, so decode "
        "is measured at that context depth (0 = off). Use this to test "
        "long-context effects like adaptive MTP.",
    )
    parser.add_argument("--startup-timeout", type=float, default=180)
    parser.add_argument("--request-timeout", type=float, default=300)
    parser.add_argument(
        "--overthink",
        action="store_true",
        help="Behavior probe instead of speed benchmark: one chat request per "
        "profile with reasoning-bait prompts; reports thinking vs answer share.",
    )
    args = parser.parse_args()
    context = require_native_execution("llama.cpp benchmark")
    print(f"[OK] Execution context: {json.dumps(context)}", flush=True)
    if launch_util.llama_server_running():
        raise RuntimeError("Stop the existing llama-server before running profile benchmarks")
    global output
    output = BenchmarkPaths(__file__).new_run()
    with report_run(
        output,
        "llamacpp/benchmark_llamacpp_profiles",
        "model-comparison",
        reasoning=BENCHMARK_REASONING_EFFORT if args.overthink else "not applicable (raw completion)",
    ):
        # - None means "whatever ACTIVE_LLAMACPP_BUILD points at"
        builds: list[str | None] = args.builds or [None]

        if args.overthink:
            prompts = {label: OVERTHINK_PROMPTS[label] for label in OVERTHINK_PROMPTS}
        else:
            prompts = {label: DEFAULT_PROMPTS[label] for label in args.prompt_set}
        output.logs.mkdir(parents=True, exist_ok=True)
        output.artifacts.mkdir(parents=True, exist_ok=True)
        summary_lines = [
            f"Benchmark started: {datetime.now().isoformat(timespec='seconds')}",
            f"Mode: {'overthink probe' if args.overthink else 'decode speed'}",
            f"Builds: {', '.join(b or cfg.LLAMACPP_ACTIVE_BUILD for b in builds)}",
            f"Profiles: {', '.join(args.profiles)}",
            f"Prompts: {', '.join(prompts)}",
            f"Max tokens: {args.max_tokens}; warmup tokens: {args.warmup_tokens}; repeats: {args.repeats}",
            f"Context fill: {'~' + str(args.ctx_fill) + ' tokens' if args.ctx_fill else 'off'}",
            "",
        ]

        if args.overthink:
            failed = run_overthink(args, builds, prompts, summary_lines)
            summary_file = write_summary(output, summary_lines, "llama-overthink-summary")
            if failed:
                raise RuntimeError(f"Profile benchmark failed; see {summary_file}")
            return

        failed, csv_rows = run_decode(args, builds, prompts, summary_lines)
        summary_file = write_summary(output, summary_lines, "llama-benchmark-summary")
        if csv_rows:
            write_csv(output, csv_rows)
        if failed:
            raise RuntimeError(f"Profile benchmark failed; see {summary_file}")


if __name__ == "__main__":
    with timed("llamacpp/benchmark_llamacpp_profiles"):
        main()
