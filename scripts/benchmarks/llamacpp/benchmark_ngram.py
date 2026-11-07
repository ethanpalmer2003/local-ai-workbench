"""Compare speculation on fresh short generation and token-sized source rewriting."""

import argparse
import ast
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import post_json
from scripts.benchmarks.llamacpp.trial import require_free_session, running_server, speculation_config
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import context_category, report_run
from scripts.benchmarks.shared.timing import timed
from scripts.config import project_config as project_cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig


@dataclass(frozen=True)
class Candidate:
    name: str
    speculation: str = "draft-mtp,ngram-mod"
    mtp: int = 2
    lookup: int = 24
    minimum: int = 24
    maximum: int = 64

    def options(self) -> dict[str, str]:
        return {
            "spec-type": self.speculation,
            "spec-draft-n-max": str(self.mtp),
            "spec-ngram-mod-n-match": str(self.lookup),
            "spec-ngram-mod-n-min": str(self.minimum),
            "spec-ngram-mod-n-max": str(self.maximum),
        }


CANDIDATES = (
    Candidate("current", minimum=48),
    Candidate("legacy", lookup=32, minimum=4, maximum=8),
    Candidate("mtp-only", speculation="draft-mtp"),
    Candidate("amd-mtp1", speculation="draft-mtp", mtp=1),
    Candidate("dense-short", minimum=16, maximum=32),
    Candidate("amd-min24"),
    Candidate("amd-deep12", mtp=12),
)


@dataclass(frozen=True)
class Settings:
    rounds: int = 1
    context_tokens: int = 1024
    output_tokens: int = 128
    timeout: float = 600


def source_block(index: int) -> str:
    return (
        f"def normalize_record_{index}(record):\n"
        f"    identifier = str(record.get('id_{index}', '')).strip()\n"
        f"    amount = int(record.get('amount_{index}', {index + 1}))\n"
        "    if amount < 0:\n        raise ValueError('negative amount')\n"
        f"    return {{'identifier': identifier, 'amount': amount, 'group': {index % 17}}}\n\n"
    )


@dataclass(frozen=True)
class Workload:
    kind: str
    prompt: str
    requested_depth: int = 0
    expected: str | None = None


def rewrite_correct(content: str, expected: str) -> bool:
    try:
        return ast.dump(ast.parse(content.strip())) == ast.dump(ast.parse(expected.strip()))
    except SyntaxError:
        return False


def workloads(base: str, settings: Settings, round_index: int) -> list[Workload]:
    files = sorted((project_cfg.SCRIPTS_DIR / "launchers").rglob("*.py"))
    context = "\n".join(f"# File: {path.name}\n{path.read_text(encoding='utf-8')}" for path in files)
    tokens = post_json(f"{base}/tokenize", {"content": context}, settings.timeout)["tokens"]
    context = post_json(f"{base}/detokenize", {"tokens": tokens[: settings.context_tokens]}, settings.timeout)[
        "content"
    ]
    target = source_block(9000 + round_index)
    return [
        Workload(
            "generation", f"Implement a Python bounded queue with capacity {11 + round_index}. Explain edge cases.", 0
        ),
        Workload(
            "rewrite",
            f"Reference module:\n{context}\nRewrite only this function, changing negative amount to invalid amount. "
            f"Return the complete function without fences or commentary.\n{target}",
            settings.context_tokens,
            target.replace("negative amount", "invalid amount"),
        ),
    ]


def warmup(lifecycle: BenchmarkLifecycle, base: str, settings: Settings) -> None:
    lifecycle.warmup(
        lambda: post_json(
            f"{base}/completion",
            {
                "prompt": "Describe a red bicycle.",
                "n_predict": 32,
                "temperature": 0,
                "cache_prompt": False,
                "ignore_eos": True,
            },
            settings.timeout,
        )
    )


def measure_workload(
    lifecycle: BenchmarkLifecycle,
    base: str,
    candidate: Candidate,
    workload: Workload,
    settings: Settings,
    output: RunPaths,
    report: dict[str, Any],
    log: Path,
    options: dict[str, str],
    round_index: int,
) -> None:
    depth = len(post_json(f"{base}/tokenize", {"content": workload.prompt}, settings.timeout)["tokens"])
    request_started = time.perf_counter()
    print(f"[REQUEST] {candidate.name}/{workload.kind}: {depth} input tokens", flush=True)
    response, timing = lifecycle.measure(
        lambda: post_json(
            f"{base}/completion",
            {
                "prompt": workload.prompt,
                "n_predict": settings.output_tokens,
                "temperature": 0,
                "seed": 42,
                "cache_prompt": False,
                "ignore_eos": workload.expected is None,
                "stop": ["\n\ndef "] if workload.expected is not None else [],
            },
            settings.timeout,
        )
    )
    result = {
        **timing,
        "candidate": candidate.name,
        "options": options,
        "round": round_index,
        "category": context_category(depth),
        "workload": workload.kind,
        "requested_context_tokens": workload.requested_depth,
        "actual_prompt_tokens": depth,
        "seconds": time.perf_counter() - request_started,
        "timings": response["timings"],
        "content": response["content"],
        "log": str(log),
        "cache_prompt": False,
        "pool_state": "after unrelated warmup" if workload.kind == "generation" else "after warmup and generation",
        "correct": rewrite_correct(response["content"], workload.expected) if workload.expected else None,
    }
    report["results"].append(result)
    print(
        f"[RESULT] {candidate.name} {result['category']}/{workload.kind} depth={depth} "
        f"correct={result['correct']} seconds={result['seconds']:.2f}",
        flush=True,
    )
    (output.artifacts / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def run_candidate(
    conf: LlamaConfig,
    output: RunPaths,
    report: dict[str, Any],
    settings: Settings,
    candidate: Candidate,
    round_index: int,
) -> None:
    print(f"[RUN] round {round_index + 1}/{settings.rounds}: {candidate.name}", flush=True)
    options = candidate.options()
    trial = speculation_config(conf, options)
    log = output.logs / f"{round_index}-{candidate.name}.log"
    setup_started = time.perf_counter()
    lifecycle = None
    try:
        with running_server(trial, log, title="Ngram comparison") as (base, _command, process):
            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{candidate.name}" if process.poll() is None else "")
            lifecycle.adopt_prepared(time.perf_counter() - setup_started)
            warmup(lifecycle, base, settings)
            for workload in workloads(base, settings, round_index):
                measure_workload(
                    lifecycle, base, candidate, workload, settings, output, report, log, options, round_index
                )
    finally:
        if lifecycle is not None:
            report.setdefault("setups", []).append(
                {key: value for key, value in lifecycle.record().items() if key != "requests"}
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--context-tokens", type=int, default=1024)
    parser.add_argument("--output-tokens", type=int, default=128)
    parser.add_argument("--candidates", nargs="+", choices=[candidate.name for candidate in CANDIDATES])
    args = parser.parse_args()
    settings = Settings(args.rounds, args.context_tokens, args.output_tokens)
    selected = tuple(candidate for candidate in CANDIDATES if not args.candidates or candidate.name in args.candidates)
    require_free_session()
    conf = LlamaConfig()
    output = BenchmarkPaths(__file__).new_run()
    report: dict[str, Any] = {
        "model": str(conf.model),
        "build": str(conf.build_dir),
        "server_capacity": int(conf.profile.extra_args["ctx-size"]),
        "results": [],
        "settings": {
            "rounds": settings.rounds,
            "context_tokens": settings.context_tokens,
            "output_tokens": settings.output_tokens,
            "temperature": 0,
            "seed": 42,
            "candidates": [candidate.name for candidate in selected],
        },
    }
    with report_run(output, "llamacpp/benchmark_ngram", "mixed-context", reasoning="not applicable (raw completion)"):
        print(f"[OUTPUT] {output.root}", flush=True)
        started = time.perf_counter()
        try:
            for round_index in range(settings.rounds):
                candidates = selected if round_index % 2 == 0 else tuple(reversed(selected))
                for candidate in candidates:
                    run_candidate(conf, output, report, settings, candidate, round_index)
            if any(result["correct"] is False for result in report["results"]):
                raise RuntimeError("One or more source rewrites failed grading; see results.json")
        finally:
            report["total_seconds"] = time.perf_counter() - started
            (output.artifacts / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    with timed("llamacpp/benchmark_ngram"):
        main()
