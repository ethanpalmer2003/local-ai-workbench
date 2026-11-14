"""Bounded CPU/Vulkan file transcription and Silero VAD checks on saved speech."""

import hashlib
import json
import os
import subprocess
import threading
import time
from typing import Any

from scripts.benchmarks.asr.shared.corpus import prepare_corpus
from scripts.benchmarks.asr.shared.metrics import word_errors
from scripts.benchmarks.shared import reporting
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.shared.resources import summarize_resources, watch_resources
from scripts.tests.shared.paths import CasePaths, RunPaths


def invoke(command: list[str], env: dict[str, str], paths: RunPaths, deadline: float, context) -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    stop = threading.Event()
    with (paths.logs / "stderr.log").open("wb") as log, BenchmarkVram(paths, context) as memory:
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=project_cfg.BASE_DIR, env=env, stdout=subprocess.PIPE, stderr=log)
        launch_util.assign_process_to_job(process.pid)
        memory.stage = "load-and-infer"
        watcher = threading.Thread(
            target=watch_resources, args=(process, stop, traces, deadline, lambda: memory.stage, started), daemon=True
        )
        watcher.start()
        try:
            stdout, _ = process.communicate(timeout=max(1, min(60, deadline - time.monotonic())))
            elapsed = time.monotonic() - started
            (paths.artifacts / "stdout.txt").write_bytes(stdout)
            if process.returncode:
                raise RuntimeError(f"CLI exit {process.returncode}; inspect {paths.logs}")
            return {"command": command, "seconds": elapsed, "output": json.loads(stdout.decode("utf-8"))}
        finally:
            stop.set()
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
            process.wait(timeout=10)
            watcher.join(timeout=5)
            (paths.artifacts / "resources.json").write_text(
                json.dumps(summarize_resources(traces), indent=2), encoding="utf-8"
            )


def main() -> None:
    context = dict(require_native_execution("Parakeet CPU/Vulkan smoke"))
    run = CasePaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    clips = prepare_corpus(run, None)
    settings = cfg.PARAKEETCPP_ASR
    hashes = {}
    for path in (settings.model, settings.vad_model):
        with path.open("rb") as source:
            hashes[str(path)] = hashlib.file_digest(source, "sha256").hexdigest()
    deadline = time.monotonic() + 180
    with report_run(
        run,
        "asr/parakeetcpp/smoke",
        "audio",
        settings={
            "execution_context": context,
            "model_hashes": hashes,
            "corpus": clips,
            "limits": "Synthetic English clips, cold CLI launches; startup/model load included. Sampled resource peaks.",
        },
    ) as report:
        reporting.record_inputs(
            report, frameworks=("asr/parakeetcpp",), models={"asr": settings.model, "vad": settings.vad_model}
        )
        for build in ("cpu", "vulkan"):
            env = {**os.environ, "PARAKEET_DEVICE": "cpu" if build == "cpu" else settings.device}
            for index, vad in enumerate((False, True)):
                clip = clips[index]
                paths = RunPaths(run.root / f"{build}-vad-{vad}")
                paths.create()
                command = [
                    str(settings.executable(build)),
                    "transcribe",
                    "--model",
                    str(settings.model),
                    "--input",
                    clip["file"],
                    "--threads",
                    str(settings.threads),
                    "--json",
                ]
                if vad:
                    command += ["--vad", "--vad-model", str(settings.vad_model)]
                result = invoke(command, env, paths, deadline, context)
                text = result["output"]["text"]
                if not text.strip():
                    raise RuntimeError("Empty transcription")
                result.update(
                    build=build, vad=vad, clip=clip["id"], status="completed", **word_errors(clip["reference"], text)
                )
                report.results.append(result)
                report.save(run)
                print(f"[OK] {build} vad={vad}: {result['seconds']:.3f}s, WER {result['wer']:.1%}: {text}", flush=True)
            paths = RunPaths(run.root / f"{build}-vad-only")
            paths.create()
            result = invoke(
                [
                    str(settings.executable(build)),
                    "vad",
                    "--model",
                    str(settings.vad_model),
                    "--input",
                    clips[0]["file"],
                    "--threads",
                    str(settings.threads),
                ],
                env,
                paths,
                deadline,
                context,
            )
            if not result["output"]["segments"]:
                raise RuntimeError("VAD detected no speech in known spoken clip")
            result.update(build=build, kind="vad", status="completed")
            report.results.append(result)
            print(f"[OK] {build} VAD-only", flush=True)


if __name__ == "__main__":
    main()
