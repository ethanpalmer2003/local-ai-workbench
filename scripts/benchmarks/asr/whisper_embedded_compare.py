"""Bounded same-model Whisper comparison: Kobold, legacy Vulkan and current Vulkan."""

import argparse
import base64
import hashlib
import json
import os
import statistics
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil
import requests

from scripts.benchmarks.asr.corpus import prepare_corpus
from scripts.benchmarks.asr.metrics import word_errors
from scripts.benchmarks.asr.requests import multipart
from scripts.benchmarks.shared import BENCHMARK_SECONDS, reporting
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared.resident_profiles import whisper_command, whisper_frameworks, whisper_model
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.shared import consent
from scripts.shared.backends import listening
from scripts.shared.resources import summarize_resources, watch_resources

PORT = 18883
THREADS = 4

STANDALONES = whisper_frameworks()
STANDALONE = STANDALONES["external"]
ENGINES = ("internal", *STANDALONES)
MODEL = whisper_model()


def command(engine: str) -> list[str]:

    return whisper_command(engine, PORT)


def transcribe(engine: str, clip: dict[str, Any], deadline: float) -> dict[str, Any]:
    audio = Path(clip["file"]).read_bytes()
    if engine == "internal":
        body = json.dumps(
            {"audio_data": base64.b64encode(audio).decode(), "langcode": "en", "suppress_non_speech": False}
        ).encode()
        endpoint, content_type = "/api/extra/transcribe", "application/json"
    else:
        body, content_type = multipart(audio)
        endpoint = "/inference"
    started = time.perf_counter()
    try:
        response = requests.post(
            f"http://127.0.0.1:{PORT}{endpoint}",
            data=body,
            headers={"Content-Type": content_type},
            timeout=min(60, deadline - time.monotonic()),
        )
        response.raise_for_status()
        value = response.json()
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "unknown"
        detail = error.response.text[:2000] if error.response is not None else ""
        raise RuntimeError(f"{engine} HTTP {status}: {detail}") from error
    seconds = time.perf_counter() - started
    text = value["text"].strip()
    return {
        "clip": clip["id"],
        "seconds": seconds,
        "rtf": seconds / clip["duration_seconds"],
        "text": text,
        **word_errors(clip["reference"], text),
    }


def run_block(
    engine: str, clips: list[dict[str, Any]], paths: RunPaths, context: dict[str, Any], repeats: int, deadline: float
) -> dict[str, Any]:

    cmd = command(engine)
    result: dict[str, Any] = {"engine": engine, "command": cmd, "status": "running", "warmups": [], "samples": []}
    env = {
        **os.environ,
        "GGML_VK_VISIBLE_DEVICES": "0",
        "OMP_NUM_THREADS": str(THREADS),
        "TEMP": str(cfg.LAUNCH.temp_dir),
        "TMP": str(cfg.LAUNCH.temp_dir),
    }
    env["PATH"] = str(Path(cmd[0]).parent) + os.pathsep + env.get("PATH", "")
    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    traces, stop = [], threading.Event()
    started = time.perf_counter()
    with (paths.logs / "server.log").open("wb") as log, BenchmarkVram(paths, context) as memory:
        process = subprocess.Popen(cmd, cwd=project_cfg.BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
        launch_util.assign_process_to_job(process.pid)
        watcher = None
        try:
            ready_deadline = min(deadline, time.monotonic() + 60)
            while not listening(PORT):
                if process.poll() is not None:
                    raise RuntimeError(f"{engine} exited with {process.returncode}; inspect server.log")
                if time.monotonic() > ready_deadline:
                    raise TimeoutError("Whisper startup exceeded its budget")
                time.sleep(0.2)
            result["startup_seconds"] = time.perf_counter() - started
            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{MODEL}" if process.poll() is None else "")
            lifecycle.adopt_prepared(result["startup_seconds"])
            workers = [
                child
                for child in psutil.Process(process.pid).children(recursive=True)
                if child.name().lower() == Path(cmd[0]).name.lower()
            ]
            pid = workers[-1].pid if workers else process.pid
            result["worker_pid"] = pid
            memory.watch_backend(engine, [pid])
            watcher = threading.Thread(
                target=watch_resources,
                args=(
                    SimpleNamespace(pid=pid, poll=process.poll),
                    stop,
                    traces,
                    deadline,
                    lambda: memory.stage,
                    started,
                ),
                daemon=True,
            )
            watcher.start()
            memory.stage = "warmup"
            # - one warmup per arm: warming every clip multiplies the run's calls for no extra signal
            lifecycle.warmup(lambda: result["warmups"].append(transcribe(engine, clips[0], deadline)))
            memory.stage = "measured"
            for repetition in range(repeats):
                for clip in clips:
                    row, timing = lifecycle.measure(lambda: transcribe(engine, clip, deadline))
                    row.update(timing)
                    row["repetition"] = repetition
                    result["samples"].append(row)
                print(f"[{engine}] repetition {repetition + 1}/{repeats} completed", flush=True)
            result["status"] = "completed"
            result["benchmark"] = lifecycle.record()
        except Exception as error:
            result.update(status="failed", error=str(error))
        finally:
            memory.stage = "cleanup"
            stop.set()
            if watcher:
                watcher.join(timeout=5)
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
            process.wait(timeout=15)
            result["resources"] = summarize_resources(traces)
            result["total_seconds"] = time.perf_counter() - started
            (paths.logs / "resources.json").write_text(json.dumps(traces, indent=2), encoding="utf-8")
    (paths.artifacts / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _summary_cell(cell: dict[str, Any]) -> str:
    """One table cell; an engine that produced no sample for a clip is named, not formatted."""
    seconds, wer = cell["median_seconds"], cell["wer"]
    if seconds is None or wer is None:
        return "unavailable"
    return f"{seconds:.3f} / {wer:.1%}"


def summarize(run: RunPaths, clips: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    engines = list(dict.fromkeys(result["engine"] for result in results))
    lines = [
        "# Whisper engine comparison",
        "",
        "| Clip | Audio seconds | " + " | ".join(f"{engine} seconds / WER" for engine in engines) + " |",
        "|---|---:|" + "---:|" * len(engines),
    ]
    aggregates = []
    for clip in clips:
        row: dict[str, Any] = {"clip": clip["id"], "duration_seconds": clip["duration_seconds"]}
        for engine in engines:
            samples = [
                sample
                for result in results
                if result["engine"] == engine
                for sample in result["samples"]
                if sample["clip"] == clip["id"]
            ]
            errors, count = (
                sum(sample["word_errors"] for sample in samples),
                sum(sample["reference_words"] for sample in samples),
            )
            seconds = [sample["seconds"] for sample in samples]
            row[engine] = {
                "median_seconds": statistics.median(seconds) if seconds else None,
                "wer": errors / count if count else None,
                "samples": len(samples),
                "transcripts": sorted({sample["text"] for sample in samples}),
            }
        aggregates.append(row)
        lines.append(
            f"| {row['clip']} | {row['duration_seconds']:.3f} | "
            + " | ".join(_summary_cell(row[engine]) for engine in engines)
            + " |"
        )
    lines += [
        "",
        "- Identical turbo Q5_0 model and prepared 16 kHz mono PCM16 inputs; Vulkan device 0, four decoder threads, "
        "English, greedy decoding, no translation/VAD/timestamps. Flash attention is off except in vulkan-fa.",
        "- One warmup per clip in each block; startup and warmups excluded from measured medians. Exact block order "
        "is recorded in report.json; OS/driver caches are not flushed.",
        "- WER normalizes case, punctuation, accents and practice/practice spelling. Repeats are latency samples, not "
        "independent accuracy examples.",
        "- Four clean synthetic English clips are a compatibility/latency screen, not an accent/noise/multilingual "
        "quality "
        "benchmark.",
        "- Server API wall time includes each engine's input handling; JSON/base64 versus multipart differs. Embedded "
        "and standalone source revisions differ.",
        "- CPU/RAM/adapter VRAM are sampled; desktop use is included in adapter totals. No LLM/TTS is loaded during "
        "this isolated ASR test.",
        "- external is the retained disabled community release; the current Vulkan build is maintained by the explicit "
        "source-build command. Provenance is in report.json.",
    ]
    (run.artifacts / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run.artifacts / "comparison.json").write_text(json.dumps(aggregates, indent=2), encoding="utf-8")


def main() -> None:

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        help="JSON list of file/reference/id entries; defaults to the last complete Kokoro comparison",
    )
    parser.add_argument(
        "--order", nargs="+", choices=ENGINES, default=["internal", "vulkan-fa", "vulkan-fa", "internal"]
    )
    parser.add_argument("--repeats", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--budget", type=int, choices=range(60, 901), default=240, help="Whole-run budget in seconds")
    args = parser.parse_args()
    context = dict(require_native_execution("Whisper embedded/standalone comparison"))
    names = {
        "koboldcpp-nocuda.exe",
        "koboldcpp.exe",
        "whisper-server.exe",
        "audiocpp_server.exe",
        "sd-server.exe",
        "llama-server.exe",
    }
    active = [
        process.info["name"]
        for process in psutil.process_iter(["name"])
        if (process.info["name"] or "").lower() in names
    ]
    if active or listening(PORT):
        raise RuntimeError(f"Existing native sessions or occupied benchmark port; no service was stopped: {active}")
    run = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    clips = prepare_corpus(run, args.corpus)
    with MODEL.open("rb") as source:
        model_hash = hashlib.file_digest(source, "sha256").hexdigest()
    settings = {
        "execution_context": context,
        "model": str(MODEL),
        "model_sha256": model_hash,
        "kobold_version": subprocess.check_output(
            [str(cfg.KOBOLDCPP_SERVICE.exe), "--version"], text=True, timeout=30
        ).strip(),
        "standalone_release_published": (STANDALONE / ".release_published_at").read_text().strip(),
        "standalone_asset": (STANDALONE / ".release_asset").read_text().strip(),
        "standalone_upstream_version": "unknown; runtime details retained in logs",
        "standalone_builds": {
            engine: json.loads((directory / ".build_manifest.json").read_text(encoding="utf-8"))
            for engine, directory in STANDALONES.items()
            if engine in args.order and (directory / ".build_manifest.json").is_file()
        },
        "threads": THREADS,
        "gpu": "Vulkan device 0",
        "flash_attention": "enabled for vulkan-fa only",
        "language": "en",
        "order": args.order,
        "repeats_per_block": args.repeats,
        "budget_seconds": args.budget,
        "corpus": clips,
        "controls": "Kobold hardcodes four decoder threads, greedy best_of=-1, beam_size=-1, max_len=100, split_on_word, "
        "no_timestamps, temperature 0 and fallback increment 0.2; standalone flags match exposed controls "
        "and retain temperature/fallback defaults.",
    }
    deadline = time.monotonic() + args.budget
    with report_run(run, "asr/shared/whisper_embedded_compare", "audio", settings=settings) as report:
        for index, engine in enumerate(args.order):
            paths = RunPaths(run.root / f"{index}-{engine}")
            paths.create()
            result = run_block(engine, clips, paths, context, args.repeats, deadline)
            report.results.append(result)
            report.save(run)
            if result["status"] != "completed":
                raise RuntimeError(result["error"])
        reporting.record_inputs(report, frameworks=("koboldcpp", "asr/whispercpp"), models={"whisper": MODEL})
        if len({result["engine"] for result in report.results}) > 1:
            summarize(run, clips, report.results)


if __name__ == "__main__":
    consent.require(BENCHMARK_SECONDS)
    main()
