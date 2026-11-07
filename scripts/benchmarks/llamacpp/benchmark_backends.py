"""Paired native-server benchmark of HRX and Lemonade with matched Swift settings."""

import argparse
import json
import statistics
import time
from dataclasses import replace
from typing import Any

from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import post_json, stop_server, wait_ready
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig


def run_trial(
    evidence: dict[str, Any],
    paths: RunPaths,
    round_index: int,
    build: str,
    prompts: dict[str, str],
    args: argparse.Namespace,
    port: int,
) -> None:
    conf = LlamaConfig(
        profile_name="swift15-hrx", build_name=build, port=port, ini_overrides={"reasoning": "off", "fit": "off"}
    )
    conf.profile = replace(
        conf.profile,
        extra_args={
            **conf.profile.extra_args,
            "ctx-size": str(args.context),
            "cache-type-k": args.cache,
            "cache-type-v": args.cache,
            "batch-size": "512",
            "ubatch-size": "512",
            "threads": "8",
            "threads-batch": "8",
        },
    )
    log = paths.logs / f"{round_index}-{build}.log"
    command = conf.build_cmd(log)
    trial: dict[str, Any] = {"round": round_index, "build": build, "command": command, "requests": []}
    evidence["trials"].append(trial)
    print(f"[RUN] round {round_index + 1}: {build}", flush=True)
    load_start = time.monotonic()
    process = launch_util.launch_process(
        command,
        title="Backend benchmark",
        cwd=str(conf.build_dir),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log),
        env=conf.build_env,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        wait_ready(base, process, 90)
        trial["startup_seconds"] = time.monotonic() - load_start
        lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{build}" if process.poll() is None else "")
        lifecycle.adopt_prepared(trial["startup_seconds"])
        lifecycle.warmup(
            lambda: post_json(
                f"{base}/completion",
                {"prompt": "Describe a green bicycle.", "n_predict": 16, "temperature": 0, "cache_prompt": False},
                120,
            )
        )
        for name, prompt in prompts.items():
            request_start = time.monotonic()
            response, timing = lifecycle.measure(
                lambda: post_json(
                    f"{base}/completion",
                    {
                        "prompt": prompt,
                        "n_predict": args.tokens,
                        "temperature": 0,
                        "seed": 42,
                        "ignore_eos": True,
                        "cache_prompt": False,
                    },
                    180,
                )
            )
            row: dict[str, Any] = {
                **timing,
                "prompt": name,
                "seconds": time.monotonic() - request_start,
                "timings": response["timings"],
                "content": response["content"],
                "tokens": response["tokens"],
            }
            trial["requests"].append(row)
            trial["benchmark"] = lifecycle.record()
            (paths.artifacts / f"{round_index}-{build}-{name}.json").write_text(
                json.dumps(response, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"[RESULT] {build}/{name}: {row['timings']['predicted_per_second']:.2f} tok/s, {row['seconds']:.2f}s",
                flush=True,
            )
            (paths.artifacts / "results.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    finally:
        stop_server(process)


def summarize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for build in ("rocm-lemonade", "hrx"):
        rows = [r for t in evidence["trials"] if t["build"] == build for r in t["requests"]]
        summary[build] = {
            "median_decode_tokens_per_second": statistics.median(r["timings"]["predicted_per_second"] for r in rows),
            "median_request_seconds": statistics.median(r["seconds"] for r in rows),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--tokens", type=int, default=64)
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--cache", choices=("f16", "q8_0"), default="f16")
    args = parser.parse_args()
    if launch_util.llama_server_running():
        raise RuntimeError("Local llama-server is running; confirm session safety before benchmarking")
    port = 9951
    if launch_util.backend_running(port):
        raise RuntimeError(f"Benchmark port {port} is occupied")
    paths = BenchmarkPaths(__file__).new_run()
    source = (project_cfg.SCRIPTS_DIR / "launchers/llamacpp/llamacpp.py").read_text(encoding="utf-8")[:4000]
    prompts = {
        "code": "int add(int a, int b) { return",
        "prose": "Explain in one clear paragraph why repeated benchmarks are useful.\nAnswer:",
        "source": f"Read this Python launcher excerpt:\n{source}\nExplain its configuration precedence in plain English.\nAnswer:",
    }
    evidence: dict[str, Any] = {"settings": vars(args), "prompts": prompts, "trials": []}
    start = time.monotonic()
    try:
        for round_index in range(args.rounds):
            order = ("rocm-lemonade", "hrx") if round_index % 2 == 0 else ("hrx", "rocm-lemonade")
            for build in order:
                run_trial(evidence, paths, round_index, build, prompts, args, port)
        summary = summarize_evidence(evidence)
        evidence["summary"] = summary
        evidence["code_matches"] = [
            evidence["trials"][i]["requests"][0]["tokens"] == evidence["trials"][i + 1]["requests"][0]["tokens"]
            for i in range(0, len(evidence["trials"]), 2)
        ]
        paths.write_report(
            {
                "name": "llamacpp/benchmark_backends",
                "category": "llamacpp",
                "status": "completed",
                "reasoning": "Matched settings; alternating fresh servers; no blanket answer-quality grading",
                "total_seconds": time.monotonic() - start,
                "summary": summary,
            }
        )
        print(json.dumps(summary, indent=2))
    finally:
        (paths.artifacts / "results.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"[OUTPUT] {paths.root}", flush=True)


if __name__ == "__main__":
    main()
