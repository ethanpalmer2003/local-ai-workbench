"""Avalon llama-server fork serving the Strata app's own GGUF weights.

- The Strata IQ2_XS pack is a standard split GGUF (arch `qwen4exp`) with the
  tokenizer and chat template embedded, so Avalon's fork loads it unmodified
- The MTP draft head is a separate 1.4 GiB file (`mtp/mtp-...gguf`), not part of
  the 89 GiB pack: it is an appended NextN block for the same base model, so it
  drives the Strata weights directly
- The expert cache needs `GGML_CUDA_MOE_CACHE_MIN_EXPERT_KB=1`: the default
  floor (1 MiB here) rejects these ~512 KiB experts, and the fork aborts
  instead of falling back to the CPU when nothing is pooled
- `--cache-ram` must be set explicitly: its default is 0 whenever the model is
  larger than RAM, which disables prompt caching and re-prefills every request
- Same prompt contract and native timing source as the llama.cpp sweep
"""

from __future__ import annotations

import os
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from scripts.benchmarks.inference_engines.engines.base import EngineOptions, EngineResult, RunSpec
from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import (
    Sample,
    await_http,
    build_filler,
    completion_request,
    stop_server,
)
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.paths import RunPaths
from scripts.benchmarks.shared.vram import snapshot_dict
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor

ALIAS = "strata-swift-iq2_xs"
IDENTIFIER = f"avalon/{ALIAS}"
MODEL_DIR = project_cfg.STRATA_MODELS_DIR / "models" / "swift-IQ2_XS"
MODEL_FILE = "Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"

# - the cache's default expert-size floor is 1 MiB on this GPU; these experts are ~512 KiB
ENV = {"GGML_CUDA_MOE_CACHE_MIN_EXPERT_KB": "1"}

# - --cache-ram defaults to 0 when the model exceeds RAM, so prompt caching is off
#   unless it is passed; 1024 MiB covers the ~3025-token prompts plus decoded tails
CACHE_RAM_MIB = "1024"


def server_exe() -> Path:
    override = os.environ.get("AVALON_SERVER")
    return Path(override) if override else project_cfg.AVALON_SERVER_EXE


def model_path() -> Path:
    return MODEL_DIR / MODEL_FILE


def mtp_path() -> Path:
    override = os.environ.get("AVALON_MTP")
    return Path(override) if override else project_cfg.AVALON_MTP_GGUF


def command(log_file: Path) -> list[str]:
    """Avalon flags for the Strata weights, mirroring the Strata run settings."""
    return [
        str(server_exe()),
        "-m",
        str(model_path()),
        "-md",
        str(mtp_path()),
        "--alias",
        ALIAS,
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
        "q4_0",
        "--spec-type",
        "draft-mtp",
        "--spec-draft-n-max",
        "2",
        "-ubd",
        "256",
        "-ctkd",
        "q8_0",
        "-ctvd",
        "q8_0",
        "--moe-cache",
        "auto",
        "--cache-ram",
        CACHE_RAM_MIB,
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


class AvalonEngine:
    name = "avalon"
    label = "Avalon"

    def runs(self, options: EngineOptions) -> list[RunSpec]:
        return [
            RunSpec(
                identifier=IDENTIFIER,
                model=str(model_path()),
                quant="IQ2_XS",
                backend="avalon",
                build="avalon",
                profile="strata-iq2_xs",
                settings={
                    "ctx_size": "65536",
                    "spec_type": "draft-mtp",
                    "moe_cache": "auto",
                    "cache_ram_mib": CACHE_RAM_MIB,
                },
            )
        ]

    def available(self, spec: RunSpec) -> tuple[bool, str]:
        exe = server_exe()
        if not exe.is_file():
            return False, f"Avalon llama-server not installed: {exe}"
        model = model_path()
        if not model.is_file():
            return False, f"Strata weights not found: {model}"
        mtp = mtp_path()
        if not mtp.is_file():
            return False, f"Avalon MTP draft head not found: {mtp}"
        return True, ""

    def run(self, spec: RunSpec, options: EngineOptions, output: RunPaths) -> EngineResult:
        if launch_util.llama_server_running() or launch_util.port_listening(cfg.LLAMACPP_SERVICE.port):
            raise RuntimeError("Existing llama.cpp session/port retained; use a free benchmark session")
        log_file = output.logs / "avalon-strata-iq2_xs.log"
        argv = command(log_file)
        base_url = f"http://127.0.0.1:{cfg.LLAMACPP_SERVICE.port}"
        baseline = snapshot_dict()
        monitor = GpuMemoryMonitor(None, output.logs / "vram-avalon-strata-iq2_xs.jsonl")
        monitor.stage = "startup"
        samples: list[Sample] = []
        warmup_seconds = 0.0
        startup_seconds = 0.0
        process = launch_util.launch_process(
            argv,
            "LLM inference benchmark",
            cwd=str(server_exe().parent),
            kill_ports=None,
            mode=cfg.ConsoleTerminalLaunchMode.MERGE,
            log_file=str(log_file),
            env=ENV,
        )
        monitor.pid = process.pid
        try:
            started = time.perf_counter()
            with monitor:
                await_http(base_url, process, options.startup_timeout)
                startup_seconds = time.perf_counter() - started
                lifecycle = BenchmarkLifecycle(
                    lambda: f"{process.pid}:{spec.identifier}" if process.poll() is None else ""
                )
                lifecycle.adopt_prepared(startup_seconds)
                filler = build_filler(options.ctx_fill)
                use_cache = not options.ctx_fill
                for label, prompt in options.prompts.items():
                    full_prompt = filler + prompt
                    monitor.stage = f"warmup-{label}"
                    warmup_started = time.perf_counter()
                    lifecycle.warmup(
                        lambda: completion_request(
                            base_url, full_prompt, options.warmup_tokens, options.request_timeout, use_cache
                        )
                    )
                    warmup_seconds += time.perf_counter() - warmup_started
                    monitor.stage = f"request-{label}"
                    for _ in range(options.repeats):
                        sample, _ = lifecycle.measure(
                            lambda: completion_request(
                                base_url, full_prompt, options.max_tokens, options.request_timeout, use_cache
                            )
                        )
                        samples.append(sample)
        finally:
            stop_server(process)

        memory = monitor.summary()
        decode = statistics.mean(sample.tokens_per_second for sample in samples) if samples else None
        timed_prefill = [sample for sample in samples if sample.prompt_seconds > 0]
        prefill = (
            sum(sample.prompt_tokens for sample in timed_prefill)
            / sum(sample.prompt_seconds for sample in timed_prefill)
            if timed_prefill
            else None
        )
        return EngineResult(
            engine=self.name,
            identifier=spec.identifier,
            model=spec.model,
            quant=spec.quant,
            backend=spec.backend,
            settings={**spec.settings, "command": argv, "baseline": baseline},
            status="completed",
            startup_seconds=startup_seconds,
            load_seconds=None,
            warmup_seconds=warmup_seconds,
            decode_tokens_per_second=decode,
            decode_scope="native_decode",
            prefill_tokens_per_second=prefill,
            vram_peak_mib=memory.get("peak_process_used_mb"),
            request_samples=[asdict(sample) for sample in samples],
            log=str(log_file),
        )
