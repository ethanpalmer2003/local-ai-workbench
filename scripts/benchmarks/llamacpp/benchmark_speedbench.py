"""Repeated paired speculation comparisons using llama.cpp's SPEED-Bench client."""

import argparse
import json
import math
import os
import runpy
import statistics
import time
from dataclasses import asdict
from typing import Any

from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import post_json
from scripts.benchmarks.llamacpp.benchmark_ngram import CANDIDATES, Candidate
from scripts.benchmarks.llamacpp.trial import require_free_session, running_server, speculation_config
from scripts.benchmarks.shared import reporting
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import BENCHMARK_REASONING_EFFORT, report_run
from scripts.benchmarks.shared.timing import timed
from scripts.config import project_config as project_cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig


def run_candidate(
    conf: LlamaConfig,
    output: RunPaths,
    bench: dict[str, Any],
    samples: list[Any],
    inputs: dict[str, Any],
    candidate: Candidate,
    round_index: int,
    rounds: int,
) -> dict[str, Any]:
    print(f"[RUN] round {round_index + 1}/{rounds}: {candidate.name}", flush=True)
    trial_started = time.perf_counter()
    options = candidate.options()
    trial = speculation_config(conf, options)
    log = output.logs / f"{round_index}-{candidate.name}.log"
    setup_started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with running_server(trial, log, title="SPEED-Bench speculation") as (base, command, process):
        lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{candidate.name}" if process.poll() is None else "")
        lifecycle.adopt_prepared(time.perf_counter() - setup_started)
        lifecycle.warmup(
            lambda: post_json(
                f"{base}/completion",
                {"prompt": "Describe a red bicycle.", "n_predict": 32, "temperature": 0, "cache_prompt": False},
                120,
            )
        )
        for sample in samples:
            result, timing = lifecycle.measure(
                lambda: bench["run_one"](sample, f"{base}/v1/chat/completions", trial.alias, 256, inputs, 120),
                accept=lambda value: value.ok,
            )
            rows.append({**asdict(result), **timing})
            (output.artifacts / f"{round_index}-{candidate.name}.json").write_text(
                json.dumps({"command": command, "options": options, "results": rows}, indent=2), encoding="utf-8"
            )
            if not result.ok:
                raise RuntimeError(result.error)
            print(
                f"[RESULT] {sample.category}: {result.predicted_per_second:.2f} tok/s, "
                f"{result.latency_s:.2f}s, input={result.prompt_tokens}",
                flush=True,
            )
    return {
        "results": rows,
        "benchmark": lifecycle.record(),
        "whole_trial_seconds": time.perf_counter() - trial_started,
    }


def build_evidence(
    args: argparse.Namespace,
    samples: list[Any],
    inputs: dict[str, Any],
    conf: LlamaConfig,
    selected: tuple[Candidate, ...],
    baseline: str,
) -> dict[str, Any]:
    return {
        "rounds": [],
        "samples": [asdict(sample) for sample in samples],
        "extra_inputs": inputs,
        "output_cap": 256,
        "model": str(conf.model),
        "build": str(conf.build_dir),
        "scope": "English/code short-input speed; no answer-quality grading",
        "target_seconds": args.seconds,
        "candidates": {candidate.name: candidate.options() for candidate in selected},
        "baseline": baseline,
    }


def compare(evidence: dict[str, Any], selected: tuple[Candidate, ...], baseline: str) -> dict[str, Any]:
    from scipy.stats import t

    comparisons = {}
    for candidate in selected:
        if candidate.name == baseline:
            continue
        ratios = [
            math.log(
                sum(row["latency_s"] for row in pair[baseline]["results"])
                / sum(row["latency_s"] for row in pair[candidate.name]["results"])
            )
            for pair in evidence["rounds"]
        ]
        mean = statistics.mean(ratios)
        interval = None
        if len(ratios) > 1:
            margin = float(t.ppf(0.975, len(ratios) - 1)) * statistics.stdev(ratios) / math.sqrt(len(ratios))
            interval = [100 * (1 - math.exp(-bound)) for bound in (mean - margin, mean + margin)]
        comparisons[candidate.name] = {
            "request_time_reduction_percent": 100 * (1 - math.exp(-mean)),
            "round_time_reduction_percent": [100 * (1 - math.exp(-value)) for value in ratios],
            "approximate_95_percent_interval": interval,
        }
    return {
        "baseline": baseline,
        "candidates": comparisons,
        "interval_method": "paired round-level log latency ratios, Student t; small-sample normality assumption",
        "defaults_changed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mtp-depths", nargs="+", type=int)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=600)
    args = parser.parse_args()
    selected = (
        tuple(Candidate(f"mtp-{depth}", mtp=depth, minimum=48) for depth in args.mtp_depths)
        if args.mtp_depths
        else CANDIDATES[:2]
    )
    baseline = selected[0].name if args.mtp_depths else "legacy"
    require_free_session()
    cache = project_cfg.CACHE_DIR / "hf-benchmarks"
    os.environ.update(HF_HOME=str(cache), HF_HUB_CACHE=str(cache / "hub"), HF_DATASETS_CACHE=str(cache / "datasets"))
    bench = runpy.run_path(str(project_cfg.BENCHMARK_TOOLS_DIR / "speed-bench/speed_bench.py"))
    samples = bench["load_samples"](argparse.Namespace(bench="qualitative", category="coding,writing", limit=2))
    output = BenchmarkPaths(__file__).new_run()
    conf = LlamaConfig()
    inputs = {
        "temperature": 0,
        "seed": 42,
        "cache_prompt": False,
        "ignore_eos": True,
        "reasoning_effort": BENCHMARK_REASONING_EFFORT,
    }
    evidence = build_evidence(args, samples, inputs, conf, selected, baseline)
    with report_run(
        output, "llamacpp/benchmark_speedbench", "low-context", reasoning=str(inputs["reasoning_effort"])
    ) as report:
        print(f"[OUTPUT] {output.root}", flush=True)
        started = time.perf_counter()
        previous_pair_seconds = 0.0
        for round_index in range(args.rounds):
            if round_index and time.perf_counter() - started + previous_pair_seconds > args.seconds:
                break
            pair_started = time.perf_counter()
            offset = round_index % len(selected)
            pair = {}
            for candidate in selected[offset:] + selected[:offset]:
                pair[candidate.name] = run_candidate(
                    conf, output, bench, samples, inputs, candidate, round_index, args.rounds
                )
            evidence["rounds"].append(pair)
            (output.artifacts / "results.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            previous_pair_seconds = time.perf_counter() - pair_started
        evidence["comparison"] = compare(evidence, selected, baseline)
        (output.artifacts / "results.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"[COMPARISON] {evidence['comparison']}", flush=True)
        reporting.record_inputs(report, frameworks=("llamacpp",), models={"chat": conf.model})


if __name__ == "__main__":
    with timed("llamacpp/benchmark_speedbench"):
        main()
