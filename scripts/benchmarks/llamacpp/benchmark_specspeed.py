"""Run the English/code specspeed probe against current and legacy ngram settings."""

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import post_json
from scripts.benchmarks.llamacpp.benchmark_ngram import CANDIDATES, Candidate
from scripts.benchmarks.llamacpp.trial import require_free_session, running_server, speculation_config
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import BENCHMARK_REASONING_EFFORT, report_run
from scripts.benchmarks.shared.timing import timed
from scripts.config import project_config as project_cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig


def run_candidate(output: RunPaths, probe: Path, conf: LlamaConfig, candidate: Candidate) -> None:
    options = candidate.options()
    trial = speculation_config(conf, options)
    log = output.logs / f"{candidate.name}-server.log"
    with running_server(trial, log, title="Specspeed comparison", guard=False, alias="qwen3.8-27b") as (base, command, _):
        post_json(
            f"{base}/completion",
            {"prompt": "Describe a red bicycle.", "n_predict": 32, "temperature": 0, "cache_prompt": False},
            600,
        )
        (output.artifacts / f"{candidate.name}-config.json").write_text(
            json.dumps({"command": command, "options": options}, indent=2), encoding="utf-8"
        )
        env = {
            **os.environ,
            "QWEN_URL": f"{base}/v1",
            "MAXTOK": "256",
            "EFFORT": BENCHMARK_REASONING_EFFORT,
            "SPEC_TAG": candidate.name,
            "SPEC_OUT": str(output.artifacts / f"{candidate.name}.json"),
            "PYTHONIOENCODING": "utf-8",
        }
        with (output.logs / f"{candidate.name}-probe.log").open("w", encoding="utf-8") as transcript:
            subprocess.run([sys.executable, str(probe)], env=env, stdout=transcript, stderr=subprocess.STDOUT, check=True)
        result = json.loads((output.artifacts / f"{candidate.name}.json").read_text(encoding="utf-8"))
        if any("err" in row for row in result["rows"]):
            raise RuntimeError(f"{candidate.name} probe returned request errors")
        print(f"[RESULT] {candidate.name}: {result['mean_gen']} tokens/sec", flush=True)


def main() -> None:
    require_free_session()
    output = BenchmarkPaths(__file__).new_run()
    probe = project_cfg.BENCHMARK_TOOLS_DIR / "specspeed/specspeed.py"
    conf = LlamaConfig()
    with report_run(output, "llamacpp/benchmark_specspeed", "low-context", reasoning=BENCHMARK_REASONING_EFFORT):
        print(f"[OUTPUT] {output.root}", flush=True)
        for candidate in CANDIDATES[:2]:
            run_candidate(output, probe, conf, candidate)


if __name__ == "__main__":
    with timed("llamacpp/benchmark_specspeed"):
        main()
