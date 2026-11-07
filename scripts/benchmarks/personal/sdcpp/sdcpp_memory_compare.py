"""Vulkan CPU offload and VAE tile trade-offs at matched generation settings."""

import argparse
import json
import re
import statistics
import time
from typing import Any

from scripts.benchmarks.personal.sdcpp.sdcpp_backend_compare import arm, preflight
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.launchers import launcher_config as cfg
from scripts.tests.shared import benchmark_config as benchmark_cfg

VARIANTS = {
    "baseline": ("--backend", "Vulkan0"),
    "text-encoder-cpu": ("--backend", "Vulkan0,te=cpu"),
    "vae-tile-512": ("--backend", "Vulkan0", "--vae-tiling", "--vae-tile-size", "512x512"),
    "vae-tile-256": ("--backend", "Vulkan0", "--vae-tiling", "--vae-tile-size", "256x256"),
    "cpu-weights-budget-8": ("--backend", "Vulkan0", "--offload-to-cpu", "--max-vram", "8"),
    "text-cpu-and-vae-512": ("--backend", "Vulkan0,te=cpu", "--vae-tiling", "--vae-tile-size", "512x512"),
}


def summarize(result: dict[str, Any], folder: RunPaths) -> dict[str, Any]:
    memory = json.loads((folder.artifacts / "vram.json").read_text())
    rows = [json.loads(line) for line in (folder.logs / "vram-adapter.jsonl").read_text().splitlines()]
    values = [row["memory"]["used_mb"] / 1024 for row in rows if row["stage"] == "measured" and row.get("memory")]
    native_log = (folder.logs / "server.log").read_text(errors="replace")
    workspace = [float(value) for value in re.findall(r"vae compute buffer size: ([\d.]+) MB\(VRAM\)", native_log)]
    resources = result.get("resources", {}).get("phases", {}).get("measured", {})
    return {
        "variant": result["variant"],
        "status": result["status"],
        "seconds": result.get("median_seconds"),
        "measured_median_vram_gib": statistics.median(values) if values else None,
        "measured_mean_vram_gib": statistics.mean(values) if values else None,
        "measured_peak_vram_gib": max(values) if values else None,
        "whole_arm_peak_vram_gib": memory["adapter"]["peak_total_used_mb"] / 1024,
        "measured_vram_samples": len(values),
        "peak_process_rss_gib": result["ram"]["peak_process_rss_bytes"] / 2**30,
        "minimum_free_ram_gib": result["ram"]["minimum_available_gib"],
        "native_vae_workspace_mb": max(workspace) if workspace else None,
        "server_cpu_percent_machine": resources.get("process_cpu_percent_machine"),
        "system_cpu_percent": resources.get("system_cpu_percent"),
        "system_disk_read_bytes_per_second": resources.get("system_disk_read_bytes_per_second"),
        "system_disk_write_bytes_per_second": resources.get("system_disk_write_bytes_per_second"),
        "process_io_read_bytes_delta": resources.get("process_io_read_bytes_delta"),
        "process_io_write_bytes_delta": resources.get("process_io_write_bytes_delta"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", choices=tuple(VARIANTS), default=list(VARIANTS))
    args = parser.parse_args()
    if len(args.variants) != len(set(args.variants)):
        parser.error("Variant names must be unique within a run")
    context = preflight()
    output = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {output.root}", flush=True)
    deadline = time.monotonic() + 900
    summaries = []
    with report_run(
        output,
        "sdcpp/sdcpp_memory_compare",
        "image",
        settings={
            "execution_context": context,
            "guards": {"minimum_free_ram_gib": benchmark_cfg.MINIMUM_FREE_RAM_GIB, "whole_run_seconds": 900},
            "model_profile": cfg.SDCPP_SERVICE.model,
            "model_path": cfg.SDCPP_SERVER_ARGS["m"],
            "variants": {name: VARIANTS[name] for name in args.variants},
            "seed": 42,
            "rng": "cpu",
            "threads": 8,
            "warmup_images_per_variant": 1,
            "measured_images_per_variant": 2,
            "controls": "same Vulkan release, model, 1024x1024, 25 steps, Euler A, CFG 4, CLIP skip 2; fresh server per variant; same two measured prompts across variants",
            "prompt_cache": "warmup and both measured prompts differ, including between measured requests; CPU encoder work not hidden by exact-prompt reuse",
            "convolution": "direct convolution fixed on to prevent autotuning confounds",
            "limits": "single ordered screen; OS/shader caches not reset; sampled whole-adapter memory includes other apps and can miss short peaks; no broad quality ranking",
        },
    ) as report:
        for variant in args.variants:
            arguments = VARIANTS[variant]
            folder = RunPaths(output.root / variant)
            folder.create()
            print(f"[VARIANT] {variant}", flush=True)
            result = arm(
                "vulkan",
                folder,
                context,
                deadline,
                (*arguments, "--conv-direct", "on", "--verbose"),
                fresh_prompts=True,
                fast_adapter_sampling=True,
            )
            result["variant"] = variant
            report.results.append(result)
            report.save(output)
            if result["status"] != "completed":
                report.status = "failed"
                raise RuntimeError(f"{variant} failed; inspect logs before continuing")
            summary = summarize(result, folder)
            summaries.append(summary)
            (output.artifacts / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
            print("[SUMMARY] " + json.dumps(summary), flush=True)
    print(f"[RESULTS] {output.artifacts}", flush=True)


if __name__ == "__main__":
    main()
