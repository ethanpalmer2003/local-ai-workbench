"""Issue #3695 harness: warm decode runs, cold prompt read and cache reuse, per Strata config."""

import argparse
import json
import secrets
import statistics
import time
from pathlib import Path
from typing import Any

from scripts.benchmarks.coding_agents.shared.benchmark_requests import stream_chat
from scripts.benchmarks.shared import preflight as preflight_check
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.strata import strata_pi

WARMUP_PROMPT = "Describe a red ball in one sentence."
COLD_TAIL = "Explain Python lists versus tuples in at least 300 words."


def cold_prompt(approx_tokens: int) -> str:
    """Deterministic filler close to the issue's 31.6K-token cold prompt."""
    parts: list[str] = []
    index = 0
    while len("".join(parts)) < approx_tokens * 3.6:
        parts.append(
            f"def example_{index}(values):\n"
            f"    return [value + {index} for value in values if value % 7 == {index % 7}]\n"
        )
        index += 1
    return "".join(parts) + "\n" + COLD_TAIL


def request(connection: strata_pi.StrataConnection, messages: list[dict[str, str]], tokens: int) -> dict[str, Any]:
    body = {
        "model": connection.config["model_name"],
        "messages": messages,
        "temperature": 0,
        "seed": 42,
        "max_tokens": tokens,
        "reasoning_effort": "none",
        "reasoning_budget_tokens": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return stream_chat(connection, body, timeout=900)


def prepare(source: strata_pi.StrataConnection, arm: RunPaths) -> strata_pi.StrataConnection:
    data: dict[str, Any] = {
        **source.config,
        "host": "127.0.0.1",
        "port": cfg.STRATA_SERVICE.port,
        "open_browser": False,
        "log": str(arm.logs / "engine.log"),
        "reasoning_effort": "none",
        "reasoning_budget_tokens": 0,
    }
    for key in ("mcp_servers", "mcpServers", "mcp"):
        data.pop(key, None)
    data["api_key"] = secret = secrets.token_hex(32)
    path = arm.temp / "server.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return strata_pi.StrataConnection(path, data, cfg.STRATA_SERVICE.port, secret)


def run_arm(label: str, source: strata_pi.StrataConnection, arm: RunPaths, args: argparse.Namespace) -> dict[str, Any]:
    launch_util.kill_processes_on_ports(cfg.STRATA_SERVICE.port)
    # - the driver frees the previous engine's VRAM asynchronously; starting at once loses the expert cache
    time.sleep(8)
    connection = prepare(source, arm)
    result: dict[str, Any] = {"label": label, "source": str(source.config_path), "status": "running"}
    started = time.perf_counter()
    process = strata_pi.start_backend(connection, arm.logs / "server.log")
    process_started = launch_util.process_start_time(process.pid)
    try:
        until = time.monotonic() + args.startup_timeout
        while time.monotonic() < until:
            if process.poll() is not None:
                raise RuntimeError(f"engine exited with {process.returncode}")
            if strata_pi.ready_model(connection):
                break
            time.sleep(1)
        else:
            raise TimeoutError("engine startup timed out")
        result["startup_seconds"] = time.perf_counter() - started
        from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle

        lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{label}" if process.poll() is None else "")
        lifecycle.adopt_prepared(result["startup_seconds"])

        # - the issue discards its first 200-token run: cold expert pages dominate it
        lifecycle.warmup(lambda: request(connection, [{"role": "user", "content": WARMUP_PROMPT}], args.decode_tokens))
        samples = []
        for index in range(args.samples):
            row, timing = lifecycle.measure(
                lambda: request(connection, [{"role": "user", "content": WARMUP_PROMPT}], args.decode_tokens)
            )
            row.update(timing)
            samples.append(row)
            speed = (row.get("accounting") or {}).get("decode_tokens_per_second")
            print(f"  decode {index + 1}/{args.samples}: {speed:.2f} tok/s", flush=True)
        rates = [rate for row in samples if (rate := (row.get("accounting") or {}).get("decode_tokens_per_second"))]
        result["decode"] = {
            "median": statistics.median(rates) if rates else None,
            "min": min(rates) if rates else None,
            "max": max(rates) if rates else None,
            "samples": rates,
        }

        prompt = cold_prompt(args.cold_tokens)
        cold = request(connection, [{"role": "user", "content": prompt}], args.cold_output_tokens)
        accounting = cold.get("accounting") or {}
        result["cold_prompt"] = {
            "prompt_tokens": accounting.get("prompt_tokens"),
            "prefill_tokens_per_second": accounting.get("prefill_tokens_per_second"),
            "ttft_seconds": accounting.get("ttft_seconds"),
        }
        print(
            f"  cold prompt: {accounting.get('prompt_tokens')} tokens at "
            f"{accounting.get('prefill_tokens_per_second')} tok/s",
            flush=True,
        )

        history = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": cold["content"] or "ok"},
            {"role": "user", "content": "Repeat the last thing you said in one short sentence."},
        ]
        reuse = request(connection, history, args.cold_output_tokens)
        reused = reuse.get("accounting") or {}
        total = reused.get("prompt_tokens") or 0
        prefilled = reused.get("prefilled_tokens") or 0
        result["reuse"] = {
            "prompt_tokens": total,
            "prefilled_tokens": prefilled,
            "reuse_percent": round(100 * (total - prefilled) / total, 1) if total else None,
        }
        result["status"] = "completed"
        print(f"  prompt reuse: {result['reuse']['reuse_percent']}% of {total} tokens", flush=True)
    finally:
        result["total_seconds"] = time.perf_counter() - started
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        launch_util.sweep_escaped_children(cfg.STRATA_SERVICE.port, process_started)
        process.wait(timeout=20)
        (arm.artifacts / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strata-config", type=Path, action="append", default=[])
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--decode-tokens", type=int, default=200)
    parser.add_argument("--cold-tokens", type=int, default=32000)
    parser.add_argument("--cold-output-tokens", type=int, default=32)
    parser.add_argument("--startup-timeout", type=float, default=300)
    args = parser.parse_args()
    context = require_native_execution("Strata reference benchmark")
    configs = args.strata_config or [cfg.STRATA_SERVICE.config_path]
    output = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {output.root}", flush=True)
    results = []
    inputs = {str(path): path for path in configs}
    preflight_check.require_paths(inputs)
    preflight_check.require_free_ports({"strata": cfg.STRATA_SERVICE.port})
    preflight_check.announce("strata reference harness")
    for index, path in enumerate(configs):
        arm = RunPaths(output.root / f"arm-{index}")
        arm.create()
        source = strata_pi.saved_connections(path)[0]
        print(f"[ARM] {path.name}", flush=True)
        results.append(run_arm(path.name, source, arm, args))
    (output.root / "artifacts").mkdir(parents=True, exist_ok=True)
    (output.root / "artifacts" / "summary.json").write_text(
        json.dumps({"execution_context": context, "results": results}, indent=2) + "\n", encoding="utf-8"
    )
    print("\n=== REFERENCE HARNESS ===")
    for result in results:
        decode = result.get("decode") or {}
        cold = result.get("cold_prompt") or {}
        reuse = result.get("reuse") or {}
        print(
            f"- {result['label']}: decode {decode.get('median')} tok/s, "
            f"prompt {cold.get('prefill_tokens_per_second')} tok/s, "
            f"reuse {reuse.get('reuse_percent')}%"
        )


if __name__ == "__main__":
    main()
