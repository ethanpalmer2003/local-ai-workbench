"""Matched Drama 3 offload screen: standalone versus idle resident Rocinante Vulkan."""

import argparse
import json
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import psutil

from scripts.benchmarks.asr import audiocpp_drama3_offload as drama3_offload
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor, GpuMemorySnapshot, get_gpu_memory_snapshot
from scripts.tests.cases.koboldcpp.kobold_audiocpp_modes import kobold_reply, split_text
from scripts.tests.shared import backends


def process_ram(pid: int | None) -> dict[str, float] | None:
    if pid is None:
        return None
    try:
        info = psutil.Process(pid).memory_info()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    return {name: getattr(info, name) / 2**20 for name in ("rss", "vms", "peak_wset", "private") if hasattr(info, name)}


class DramaMemoryMonitor(GpuMemoryMonitor):
    def __init__(self, path: Path, kobold_pid: int | None) -> None:
        super().__init__(None, path)
        self.kobold_pid = kobold_pid

    def _sample(self, reader: Callable[[], GpuMemorySnapshot | None] | None = None) -> dict[str, Any]:
        sample = super()._sample(reader)
        memory = psutil.virtual_memory()
        sample["ram"] = {
            "system_total_mb": memory.total / 2**20,
            "system_available_mb": memory.available / 2**20,
            "drama": process_ram(self.pid),
            "kobold": process_ram(self.kobold_pid),
        }
        return sample

    def summary(self) -> dict[str, Any]:
        result = super().summary()
        ram = [sample["ram"] for sample in self.samples if sample.get("ram")]
        available = [sample["system_available_mb"] for sample in ram]
        result["ram"] = {
            "units": "MiB",
            "samples": len(ram),
            "minimum_system_available_mb": min(available) if available else None,
            "processes": {
                name: {
                    field: max(
                        (sample[name][field] for sample in ram if sample[name] is not None and field in sample[name]),
                        default=None,
                    )
                    for field in ("rss", "private", "peak_wset")
                }
                for name in ("drama", "kobold")
            },
        }
        return result


def save(run: RunPaths, report: dict[str, Any]) -> None:
    (run.artifacts / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    resources = {
        "execution_context": report["execution_context"],
        "cases": [
            {
                "condition": item["condition"],
                "cpu_expert_layers": item["cpu_expert_layers"],
                "process_id": item.get("process_id"),
                "execution_context": item.get("execution_context"),
                "baseline": item.get("baseline"),
                "memory": item.get("memory"),
            }
            for item in report["results"]
        ],
    }
    (run.artifacts / "vram.json").write_text(json.dumps(resources, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Drama 3 solo versus resident Rocinante",
        "",
        "- Q2 experts; clone reference; Vulkan; 2048 context; eight AudioCpp threads.",
        "- Same Rocinante-generated text, seed and request cap; startup/warmup excluded from measured requests.",
        "- Rocinante generation finishes before TTS; the combined condition keeps its model/KV cache resident.",
        "",
        "| Condition | CPU layers | Audio / gen second | First audio (s) | Drama VRAM peak (GiB) | GPU total peak (GiB) | Drama RAM RSS peak (GiB) | Min free RAM (GiB) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["results"]:
        if item.get("error"):
            lines.append(f"| {item['condition']} | {item['cpu_expert_layers']} | failed | | | | | |")
            continue
        req = item["request"]
        memory = item["memory"]
        stage = memory["stage_peaks"].get("request", {})
        values = [
            req["audio_seconds_per_second"],
            req["first_audio_s"],
            None if stage.get("process_used_mb") is None else stage["process_used_mb"] / 1024,
            None if stage.get("total_used_mb") is None else stage["total_used_mb"] / 1024,
            None
            if memory["ram"]["processes"]["drama"]["rss"] is None
            else memory["ram"]["processes"]["drama"]["rss"] / 1024,
            None
            if memory["ram"]["minimum_system_available_mb"] is None
            else memory["ram"]["minimum_system_available_mb"] / 1024,
        ]
        lines.append(
            f"| {item['condition']} | {item['cpu_expert_layers']} | "
            + " | ".join("unavailable" if value is None else f"{value:.2f}" for value in values)
            + " |"
        )
    lines.extend(
        [
            "",
            "- GPU table: sampled request-stage peaks. RAM: sampled peaks/minima across loading, warmup and request.",
            "- Windows process GPU allocations differ from physical GPU usage; peaks may miss transients.",
            "- One warmed request per case; listen to WAVs for quality. Browser playback is unmeasured.",
            "- Configs: ../temp/; WAVs and full results: this folder; GPU/RAM traces and backend logs: ../logs/.",
        ]
    )
    (run.artifacts / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    context = require_native_execution("Drama 3/Rocinante offload comparison")
    print(json.dumps(context), flush=True)
    paths = RunPaths(args.resume_run.resolve()) if args.resume_run else BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {paths.root}", flush=True)
    started = time.monotonic()
    for backend in ("audio", "image"):
        backends.require_free(backend)
    if backends.listening(drama3_offload.PORT) or launch_util.llama_server_running():
        raise RuntimeError("A model service is active; refusing a contaminated solo comparison")
    estimates = drama3_offload.weight_estimates()
    (paths.artifacts / "weight-estimates.json").write_text(json.dumps(estimates, indent=2), encoding="utf-8")
    report: dict[str, Any] = {
        "execution_context": context,
        "results": [],
        "cpu_layers": args.layers,
        "conditions": "Drama solo versus Rocinante resident and idle; no overlapping LLM generation.",
        "kobold_model": cfg.KOBOLDCPP_SERVICE.model,
        "kobold_settings": cfg.KOBOLDCPP_KCPPS_ARGS,
        "audiocpp_exe": str(project_cfg.AUDIOCPP_SERVER_EXE),
        "time_budget_reached": False,
    }
    if args.resume_run:
        report = json.loads((paths.artifacts / "results.json").read_text(encoding="utf-8"))
        if sorted(report["cpu_layers"]) != sorted(args.layers):
            raise ValueError("Resume layer choices must match the recorded matrix")
        history = report.setdefault("resumes", [])
        (paths.artifacts / f"results-before-resume-{len(history) + 1}.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        history.append(
            {
                "execution_context": context,
                "completed_cases": len(report["results"]),
                "previous_elapsed_s": report.get("elapsed_s"),
            }
        )
    try:
        combined = {r["cpu_expert_layers"] for r in report["results"] if r["condition"] == "kobold-resident"}
        if not set(args.layers).issubset(combined):
            with backends.owned_backend_sessions(paths, ("kobold",), True):
                generated = kobold_reply(45, 180)
                text = report.get("speech_text") or " ".join(split_text(generated["text"], "sentences")[:3])
                report.setdefault("generated", generated)
                report["speech_text"] = text
                (paths.artifacts / "speech-text.txt").write_text(text + "\n", encoding="utf-8")
                pids = launch_util.listening_process_ids(backends.kobold_port())
                if len(pids) != 1:
                    raise RuntimeError(f"Cannot identify one Kobold listener: {pids}")
                snapshot = get_gpu_memory_snapshot(pids[0])
                report["kobold_ready_vram"] = None if snapshot is None else asdict(snapshot)
                measure_cases(args, paths, report, "kobold-resident", text, pids[0], started)
        deadline = time.monotonic() + 10
        while backends.listening(backends.kobold_port()) and time.monotonic() < deadline:
            time.sleep(0.2)
        if backends.listening(backends.kobold_port()):
            raise RuntimeError("Kobold is still running; solo cases require it to be stopped")
        measure_cases(args, paths, report, "solo", report["speech_text"], None, started)
    except Exception:
        report["error"] = traceback.format_exc()
        raise
    finally:
        report["elapsed_s"] = time.time() - int(paths.root.name) / 1e9
        save(paths, report)
        paths.write_report(
            {
                "name": "Drama 3 CPU offload with/without Rocinante",
                "category": "probes",
                "status": "incomplete"
                if len(report["results"]) != 2 * len(args.layers)
                else "failed"
                if any(r.get("error") for r in report["results"])
                else "completed",
                "total_seconds": report["elapsed_s"],
                "reasoning": "Matched offload screen with automatic RAM/VRAM sampling; no simultaneous LLM/TTS generation.",
            }
        )
        print(paths.artifacts, flush=True)


def measure_cases(
    args: argparse.Namespace,
    paths: RunPaths,
    report: dict[str, Any],
    condition: str,
    text: str,
    kobold_pid: int | None,
    started: float,
) -> None:
    for layers in sorted(args.layers, reverse=True):
        if any(r["condition"] == condition and r["cpu_expert_layers"] == layers for r in report["results"]):
            continue
        if time.monotonic() - started > args.budget_seconds - 200:
            report["time_budget_reached"] = True
            break
        label = f"{condition}-cpu-{layers}"
        print(f"[CASE] {label}", flush=True)
        monitor = DramaMemoryMonitor(paths.logs / f"vram-{label}.jsonl", kobold_pid)
        result = drama3_offload.run_case(layers, paths, args.timeout, text, args.max_tokens, label, monitor)
        result["condition"] = condition
        report["results"].append(result)
        save(paths, report)
        if result.get("error"):
            print(
                "[WARN] Stopping this condition after failure; lower CPU offload would need more GPU memory.",
                flush=True,
            )
            break


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idle-residency", action="store_true", help="explicitly run the retired idle-only experiment")
    parser.add_argument("--layers", type=int, nargs="+", choices=range(1, 41), default=[36, 38, 40])
    parser.add_argument("--timeout", type=float, default=100)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--budget-seconds", type=float, default=900)
    parser.add_argument("--resume-run", type=Path, help="reuse saved speech and skip recorded cases")
    args = parser.parse_args()
    if not args.idle_residency:
        parser.error("Retired idle-only comparison; does not test live Kobold-to-Drama generation")
    run(args)


if __name__ == "__main__":
    main()
