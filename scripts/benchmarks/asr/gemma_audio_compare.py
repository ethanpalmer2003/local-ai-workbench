"""Same-weight Gemma audio comparison under llama.cpp and KoboldCpp."""

import base64
import hashlib
import json
import os
import statistics
import subprocess
import threading
import time
from types import SimpleNamespace
from typing import Any

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.koboldcpp import gemma_audio as gemma_kobold
from scripts.launchers.asr.llamacpp import gemma_audio
from scripts.launchers.koboldcpp import kobold
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.tests.cases.asr.shared.corpus import prepare_corpus
from scripts.tests.cases.asr.shared.metrics import word_errors
from scripts.tests.shared.resources import summarize_resources, watch_resources


def run_arm(
    engine: str, clips: list[dict[str, Any]], paths: RunPaths, context: dict[str, Any], deadline: float
) -> dict[str, Any]:
    import psutil

    backend = gemma_audio if engine == "llamacpp" else gemma_kobold
    command = gemma_audio.command() if engine == "llamacpp" else kobold.server_command()
    result: dict[str, Any] = {"engine": engine, "command": command, "samples": [], "warmups": []}
    traces, stop = [], threading.Event()
    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(cfg.LAUNCH.temp_dir), "TMP": str(cfg.LAUNCH.temp_dir)}
    with (paths.logs / "server.log").open("wb") as log, BenchmarkVram(paths, context) as memory:
        process = subprocess.Popen(command, cwd=project_cfg.BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
        launch_util.assign_process_to_job(process.pid)
        watcher = None
        started = time.perf_counter()
        try:
            while not backend.ready():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"{engine} startup failed; inspect {paths.logs}")
                time.sleep(0.2)
            result["startup_seconds"] = time.perf_counter() - started
            lifecycle = BenchmarkLifecycle(
                lambda: f"{process.pid}:{cfg.GEMMA_AUDIO_ASR.model}" if process.poll() is None else ""
            )
            lifecycle.adopt_prepared(result["startup_seconds"])
            children = [
                p
                for p in psutil.Process(process.pid).children(recursive=True)
                if p.name().lower() == cfg.KOBOLDCPP_SERVICE.exe.name.lower()
            ]
            pid = children[-1].pid if children else process.pid
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
            for index, clip in enumerate([clips[0], *clips, *clips]):
                memory.stage = "warmup" if index == 0 else "measured"
                body = json.dumps(
                    {
                        "audio_data": base64.b64encode(
                            project_cfg.BASE_DIR.joinpath(clip["file"]).read_bytes()
                        ).decode(),
                        "langcode": "en",
                    }
                ).encode()
                tick = time.perf_counter()
                timing = {}
                if index == 0:
                    values = []
                    lifecycle.warmup(
                        lambda: values.append(backend.transcribe(body, "application/json")), includes_model_load=True
                    )
                    data, _ = values[0]
                else:
                    (data, _), timing = lifecycle.measure(lambda: backend.transcribe(body, "application/json"))
                elapsed = time.perf_counter() - tick
                text = json.loads(data)["text"]
                if not text.strip():
                    raise RuntimeError(f"{engine} returned empty transcription")
                row = {
                    **timing,
                    "clip": clip["id"],
                    "seconds": elapsed,
                    "duration_seconds": clip["duration_seconds"],
                    "rtf": elapsed / clip["duration_seconds"],
                    "text": text,
                    **word_errors(clip["reference"], text),
                }
                result["warmups" if index == 0 else "samples"].append(row)
                print(f"[{engine}] {clip['id']}: {elapsed:.3f}s", flush=True)
            result["status"] = "completed"
            result["benchmark"] = lifecycle.record()
        finally:
            stop.set()
            if watcher:
                watcher.join(timeout=5)
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
            process.wait(timeout=15)
            result["resources"] = summarize_resources(traces)
    (paths.artifacts / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    import numpy as np
    import psutil
    import soundfile as sf

    context = dict(require_native_execution("Gemma audio runtime comparison"))
    if launch_util.llama_server_running():
        raise RuntimeError("Existing llama.cpp session retained; close it before this isolated comparison")
    names = {"koboldcpp-nocuda.exe", "llama-server.exe", "whisper-server.exe", "audiocpp_server.exe", "sd-server.exe"}
    active = [p.info for p in psutil.process_iter(["pid", "name"]) if (p.info["name"] or "").lower() in names]
    if active or any(launch_util.port_listening(port) for port in (18891, 18892)):
        raise RuntimeError(f"Existing native sessions/test ports; nothing was stopped: {active}")
    cfg.KOBOLDCPP_SERVICE.model = "llamacpp/gemma-4-E4B-it-Q4_0"
    cfg.KOBOLDCPP_SERVICE.transcription_engine = cfg.AsrStartupEngine.GEMMA_KOBOLD
    cfg.KOBOLDCPP_KCPPS_ARGS.update(port=18891, port_param=18891, contextsize=8192, threads=4)
    cfg.GEMMA_AUDIO_ASR.port = 18892
    run = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    clips = prepare_corpus(run, None)
    arrays = [sf.read(clips[index]["file"], dtype="float32")[0] for index in (1, 0, 3)]
    audio = np.concatenate(arrays)
    audio = np.pad(audio, (0, 30 * 16000 - len(audio)))
    file = run.artifacts / "clip-30-seconds.wav"
    sf.write(file, audio, 16000, subtype="PCM_16")
    clips.append(
        {
            "id": "30-seconds",
            "file": str(file),
            "duration_seconds": 30.0,
            "reference": " ".join(clips[index]["reference"] for index in (1, 0, 3)),
        }
    )
    integrity = {}
    for path in (cfg.GEMMA_AUDIO_ASR.model, cfg.GEMMA_AUDIO_ASR.mmproj):
        with path.open("rb") as source:
            integrity[str(path)] = hashlib.file_digest(source, "sha256").hexdigest()
    if integrity[str(cfg.GEMMA_AUDIO_ASR.mmproj)] != "197f49a93027f9843772bd24a6a9e0be2a32a788de5a3def330e9c585d86edd1":
        raise RuntimeError("Gemma projector checksum differs from upstream metadata")
    deadline = time.monotonic() + 240
    with report_run(
        run,
        "asr/shared/gemma_audio_compare",
        "audio",
        settings={
            "execution_context": context,
            "sha256": integrity,
            "clips": clips,
            "controls": "Same Q4_0 main weights, Q8_0 projector, 8192 context, 4 threads, GPU 0, strict ASR prompt, temperature 0, one warmup excluded; runtime revisions and kernels differ",
        },
    ) as report:
        for engine in ("llamacpp", "koboldcpp"):
            paths = RunPaths(run.root / engine)
            paths.create()
            report.results.append(run_arm(engine, clips, paths, context, deadline))
            report.save(run)
        summary = {
            result["engine"]: {
                "short_clip_median_seconds": statistics.median(
                    row["seconds"] for row in result["samples"] if row["duration_seconds"] < 12
                ),
                "long_clip_median_seconds": statistics.median(
                    row["seconds"] for row in result["samples"] if row["duration_seconds"] == 30
                ),
                "wer": sum(row["word_errors"] for row in result["samples"])
                / sum(row["reference_words"] for row in result["samples"]),
            }
            for result in report.results
        }
        (run.artifacts / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
