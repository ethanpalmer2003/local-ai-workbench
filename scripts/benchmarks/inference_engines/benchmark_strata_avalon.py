"""Paired Strata vs Avalon screen on the same Strata Swift IQ2_XS weights.

- Both arms use the `strata_profiles` request contract: 100-function Python
  prefix, 128 output tokens, temperature 0, seed 42, reasoning off
- Strata keeps its configured features (MTP spec 4, expert cache, int8 KV);
  Avalon runs its own shared MTP head (`draft-mtp`) and expert cache, with
  q8_0 KV to match int8
- Native timings only (`timings.predicted_per_second` from each server), so
  the two decode numbers share one scope; feature differences stay explicit
- The first measured-prompt sample per arm is discarded: it pays the cold
  expert pages and is not comparable to the rest
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import statistics
import time
import urllib.request
from pathlib import Path
from typing import Any

from scripts.benchmarks.coding_agents.shared.benchmark_requests import observe_chunk, summarize_requests
from scripts.benchmarks.coding_agents.strata_profiles import PREFIX
from scripts.benchmarks.inference_engines.engines import avalon
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor
from scripts.launchers.strata import strata_pi
from scripts.shared.wait import http_ready, wait_ready

WARMUP = "Describe a red ball in one sentence."
CONTRACT = "strata_profiles: prefix 100 Python functions, 128 tokens, temperature 0, seed 42, reasoning off"

STRATA_PROMPT = re.compile(r"prompt (\d+) tokens = (\d+) reused \+ (\d+) read")
AVALON_PROMPT = re.compile(
    r"new prompt, n_ctx_slot = \d+, n_keep = 0, task\.n_tokens =\s*(\d+).*?cached n_tokens =\s*(\d+)", re.DOTALL
)


def prompt_reuse(log_file: Path, engine: str) -> dict[str, Any]:
    """Read how many prompt tokens each engine reused instead of re-prefilling."""
    text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.is_file() else ""
    rows: list[dict[str, int]] = []
    if engine == "strata":
        for total, reused, read in STRATA_PROMPT.findall(text):
            rows.append({"prompt_tokens": int(total), "reused": int(reused), "read": int(read)})
    else:
        for prompt_tokens, reused in AVALON_PROMPT.findall(text):
            rows.append(
                {"prompt_tokens": int(prompt_tokens), "reused": int(reused), "read": int(prompt_tokens) - int(reused)}
            )
    reused = [row["reused"] for row in rows]
    return {
        "requests": len(rows),
        "reused_tokens": reused,
        "median_reused": statistics.median(reused) if reused else None,
        "total_read": sum(row["read"] for row in rows),
    }


TURNS = [
    "Summarize what these helper functions have in common.",
    "Which of them would you rewrite for clarity, and why?",
    "Add a short docstring to the pattern they share.",
    "What edge cases would break that shared pattern?",
    "Give a one-paragraph review of the conventions used here.",
]
# - a fixed stand-in for the model's earlier answers, so each turn's prompt is a
#   byte-exact prefix of the next; the content only has to be stable, not real
REPLY = "Noted: they all filter with `value % k` and rebuild the list each call."


def prompt(index: int, conversation: bool = False) -> str:
    """A single divergent request, or the next turn of one growing conversation.

    Real coding agents resend the whole history each turn: the prefix grows, the
    earlier turns stay byte-identical, so checkpoint reuse past that prefix is
    exactly what `--cache-ram` / `--prompt-cache` have to buy.
    """
    if conversation:
        turns = TURNS[: index + 1]
        body = "\n".join(f"User: {turn}\nAssistant: {REPLY}" for turn in turns[:-1])
        last = f"User: {turns[-1]}\nAssistant:"
        return PREFIX + "\n" + (body + "\n" if body else "") + last
    return PREFIX + f"\nSample {index}: explain Python lists versus tuples in at least 300 words."


SYSTEM = {"role": "system", "content": "Follow the request precisely. Do not use tools."}


def plain(text: str) -> list[dict[str, str]]:
    return [SYSTEM, {"role": "user", "content": text}]


def conversation_messages(index: int) -> list[dict[str, str]]:
    out = plain(PREFIX + "\n" + TURNS[0])
    for turn in TURNS[1 : index + 1]:
        out += [{"role": "assistant", "content": REPLY}, {"role": "user", "content": turn}]
    return out


def stream_chat(
    base_url: str, api_key: str, model: str, messages: list[dict[str, str]], tokens: int, timeout: float
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "seed": 42,
        "max_tokens": tokens,
        "reasoning_effort": "none",
        "reasoning_budget_tokens": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    query = urllib.request.Request(base_url + "/chat/completions", json.dumps(body).encode(), headers)
    started = time.perf_counter()
    record: dict[str, Any] = {"content": "", "finished": False, "output_limit": tokens}
    with urllib.request.urlopen(query, timeout=timeout) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                record["finished"] = True
                break
            chunk = json.loads(payload)
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            observe_chunk(record, chunk, time.perf_counter() - started)
            for choice in chunk.get("choices", []):
                record["content"] += choice.get("delta", {}).get("content") or ""
                if choice.get("finish_reason"):
                    record["finish_reason"] = choice["finish_reason"]
    record["seconds"] = time.perf_counter() - started
    record["accounting"] = summarize_requests([record])
    return record


def measure(
    name: str, output: RunPaths, base_url: str, api_key: str, model: str, args: argparse.Namespace
) -> dict[str, Any]:
    conversation = args.conversation
    warmup_msgs = conversation_messages(0) if conversation else plain(WARMUP)
    warmup = stream_chat(base_url, api_key, model, warmup_msgs, 32, args.request_timeout)
    discarded = []
    samples = []
    total = args.warmup_samples + args.samples
    for index in range(total):
        # - in conversation mode the warmup already sent turn 0, so measured turns
        #   continue from it: the earlier turns are a byte-exact prefix of this one
        turn = index + 1 if conversation else index
        msgs = conversation_messages(turn) if conversation else plain(prompt(turn))
        row = stream_chat(base_url, api_key, model, msgs, args.tokens, args.request_timeout)
        if index < args.warmup_samples:
            row["sample"] = index
            discarded.append(row)
            print(f"  {name} warmup sample {index + 1}/{total} discarded ({row['seconds']:.2f}s)", flush=True)
            continue
        row["sample"] = index - args.warmup_samples
        samples.append(row)
        timings = row.get("native_timings") or {}
        print(
            f"  {name} sample {row['sample'] + 1}/{args.samples}: {row['seconds']:.2f}s"
            f" | prefill {timings.get('prompt_per_second', 0):.1f} tok/s"
            f" | decode {timings.get('predicted_per_second', 0):.2f} tok/s"
            f" | ttft {row.get('first_token_seconds') or 0:.1f}s",
            flush=True,
        )
    rates = [(row.get("native_timings") or {}).get("predicted_per_second") for row in samples]
    available = [value for value in rates if value is not None]
    prefill = [(row.get("native_timings") or {}).get("prompt_per_second") for row in samples]
    prefill_available = [value for value in prefill if value is not None]
    ttft = [row.get("first_token_seconds") for row in samples]
    ttft_available = [value for value in ttft if value is not None]
    return {
        "warmup": warmup,
        "discarded_samples": discarded,
        "samples": samples,
        "native_decode_tok_s": {
            "median": statistics.median(available) if available else None,
            "mean": statistics.mean(available) if available else None,
            "min": min(available) if available else None,
            "max": max(available) if available else None,
            "count": len(available),
        },
        "prefill_tok_s": {
            "median": statistics.median(prefill_available) if prefill_available else None,
            "mean": statistics.mean(prefill_available) if prefill_available else None,
        },
        "ttft_seconds": {
            "median": statistics.median(ttft_available) if ttft_available else None,
            "mean": statistics.mean(ttft_available) if ttft_available else None,
        },
    }


def strata_arm(output: RunPaths, args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    source = strata_pi.saved_connections(cfg.STRATA_SERVICE.config_path)[0]
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
    if args.strata_cache_floor_mib is not None:
        data["args"] += ["--conversation-cache-min-free-mib", str(args.strata_cache_floor_mib)]
    if args.strata_resident_experts and "--resident-cpu-experts" not in data["args"]:
        data["args"].append("--resident-cpu-experts")
    if args.strata_kv_grow and "--kv-grow" not in data["args"]:
        data["args"].append("--kv-grow")
    key = secrets.token_hex(32)
    data["api_key"] = key
    runtime = output.temp / "strata-server.json"
    runtime.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    connection = strata_pi.StrataConnection(runtime, data, cfg.STRATA_SERVICE.port, key)
    (output.artifacts / "strata-config.json").write_text(json.dumps(source.config, indent=2) + "\n", encoding="utf-8")

    process = strata_pi.start_backend(connection, output.logs / "strata-server.log")
    process_started = launch_util.process_start_time(process.pid)
    monitor = GpuMemoryMonitor(process.pid, output.logs / "vram-strata.jsonl")
    monitor.stage = "startup"
    result: dict[str, Any] | None = None
    try:
        started = time.perf_counter()
        with monitor:
            wait_ready(
                lambda: strata_pi.ready_model(connection) is not None,
                args.startup_timeout,
                label="Strata",
                process=process,
                interval=1,
            )
            startup = time.perf_counter() - started
            monitor.stage = "measured"
            result = measure("strata", output, connection.base_url, key, data["model_name"], args)
            result["startup_seconds"] = startup
            result["command"] = data["args"]
            result["features"] = (
                "MTP spec, expert cache, KV int8, mmap-experts"
                + (" + kv-grow" if args.strata_kv_grow else "")
                + (" + resident-cpu-experts" if args.strata_resident_experts else "")
            )
        result["vram"] = monitor.summary()
        return result, source.config
    finally:
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        launch_util.sweep_escaped_children(cfg.STRATA_SERVICE.port, process_started)
        process.wait(timeout=15)
        if result is not None:
            result["prompt_reuse"] = prompt_reuse(output.logs / "engine.log", "strata")


def avalon_arm(output: RunPaths, args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    log_file = output.logs / "avalon-server.log"
    argv = [
        str(avalon.server_exe()),
        "-m",
        str(avalon.model_path()),
        "-md",
        str(avalon.mtp_path()),
        "--alias",
        avalon.ALIAS,
        "-c",
        "65536",
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
        str(args.draft_n_max),
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
        str(cfg.LLAMACPP_SERVICE.port),
        "-lv",
        str(cfg.LLAMACPP_SERVICE.verbosity),
        "--log-file",
        str(log_file),
    ]
    process = launch_util.launch_process(
        argv,
        "Strata vs Avalon benchmark",
        cwd=str(avalon.server_exe().parent),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log_file),
        env=avalon.ENV,
    )
    monitor = GpuMemoryMonitor(process.pid, output.logs / "vram-avalon.jsonl")
    monitor.stage = "startup"
    process_started = launch_util.process_start_time(process.pid)
    base_url = f"http://127.0.0.1:{cfg.LLAMACPP_SERVICE.port}/v1"
    result: dict[str, Any] | None = None
    try:
        started = time.perf_counter()
        with monitor:
            wait_ready(
                lambda: http_ready(f"http://127.0.0.1:{cfg.LLAMACPP_SERVICE.port}/health", timeout=2),
                args.startup_timeout,
                label="Avalon",
                process=process,
                interval=1,
            )
            startup = time.perf_counter() - started
            monitor.stage = "measured"
            result = measure("avalon", output, base_url, "", avalon.ALIAS, args)
            result["startup_seconds"] = startup
            result["command"] = argv
            result["features"] = (
                f"MTP draft head; expert cache on via GGML_CUDA_MOE_CACHE_MIN_EXPERT_KB=1 "
                f"(experts system-memory resident); --cache-ram {avalon.CACHE_RAM_MIB} MiB"
            )
        result["vram"] = monitor.summary()
        return result, {}
    finally:
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        launch_util.sweep_escaped_children(cfg.LLAMACPP_SERVICE.port, process_started)
        process.wait(timeout=15)
        if result is not None:
            result["prompt_reuse"] = prompt_reuse(log_file, "avalon")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument(
        "--warmup-samples", type=int, default=1, help="Measured-prompt samples to run and discard (cold pages)."
    )
    parser.add_argument("--draft-n-max", type=int, default=2, help="Avalon MTP draft depth (--spec-draft-n-max).")
    parser.add_argument("--tokens", type=int, default=128)
    parser.add_argument("--startup-timeout", type=float, default=180)
    parser.add_argument("--request-timeout", type=float, default=600)
    parser.add_argument("--order", choices=("strata-first", "avalon-first"), default="strata-first")
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=("strata", "avalon"),
        default=["strata", "avalon"],
        help="Arms to run; default both.",
    )
    parser.add_argument(
        "--strata-cache-floor-mib",
        type=int,
        default=None,
        help="Strata --conversation-cache-min-free-mib; omit to keep the engine default (2560).",
    )
    parser.add_argument(
        "--strata-resident-experts",
        action="store_true",
        help="Add --resident-cpu-experts: keep the experts the GPU cache misses in RAM instead of re-reading them from file.",
    )
    parser.add_argument(
        "--conversation",
        action="store_true",
        help="Grow one conversation across samples (real agent pattern) instead of diverging after the shared prefix.",
    )
    parser.add_argument(
        "--strata-kv-grow",
        action="store_true",
        help="Add --kv-grow: allocate KV only for cells requests reach, giving the freed VRAM to expert slots.",
    )
    args = parser.parse_args()

    context = require_native_execution("Strata vs Avalon benchmark")
    selected_ports = {"strata": cfg.STRATA_SERVICE.port, "avalon": cfg.LLAMACPP_SERVICE.port}
    # - A benchmark run owns the host: whatever holds its ports is stopped, not reported.
    for name in args.engines:
        port = selected_ports[name]
        if launch_util.port_listening(port):
            pids = launch_util.listening_process_ids(port)
            print(f"[INFO] Stopping process on port {port}: {', '.join(str(pid) for pid in pids) or 'unknown'}")
            launch_util.kill_processes_on_ports(port)

    output = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {output.root}", flush=True)
    arms = {"strata": strata_arm, "avalon": avalon_arm}
    order = ["strata", "avalon"] if args.order == "strata-first" else ["avalon", "strata"]
    order = [name for name in order if name in args.engines]
    with report_run(
        output,
        "llm/benchmark_strata_avalon",
        "llm-inference",
        settings={
            "execution_context": context,
            "arguments": vars(args),
            "contract": CONTRACT,
            "prompt_mode": "conversation" if args.conversation else "divergent-samples",
            "limitations": [
                "Strata keeps MTP and its expert cache; Avalon runs its own MTP head and expert cache",
                "The first measured-prompt sample per arm is discarded as a cold-pages warmup",
                "Avalon KV is q8_0/q8_0 to match Strata's int8; Strata's own profile is unchanged",
                "Single ordered pair, not a ranking; filesystem/page cache not reset between arms",
                "Short actual input; 64K capacity, one sample prompt prefix reused",
            ],
        },
    ) as report:
        for name in order:
            print(f"[ARM] {name}", flush=True)
            result, config = arms[name](output, args)
            report.results.append({"arm": name, **result, "config": config})
            report.save(output)
            median = result["native_decode_tok_s"]["median"]
            prefill = result["prefill_tok_s"]["median"]
            ttft = result["ttft_seconds"]["median"]
            print(
                f"[RESULT] {name}: decode {median:.2f} tok/s | prefill {prefill:.1f} tok/s | ttft {ttft:.1f}s"
                if median is not None
                else f"[RESULT] {name}: no timings",
                flush=True,
            )
        summary = {
            "contract": CONTRACT,
            "native_decode_medians": {row["arm"]: row["native_decode_tok_s"]["median"] for row in report.results},
            "prefill_medians": {row["arm"]: row["prefill_tok_s"]["median"] for row in report.results},
            "ttft_medians": {row["arm"]: row["ttft_seconds"]["median"] for row in report.results},
            "startup_seconds": {row["arm"]: row["startup_seconds"] for row in report.results},
            "prompt_reuse": {row["arm"]: row.get("prompt_reuse") for row in report.results},
        }
        (output.artifacts / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
