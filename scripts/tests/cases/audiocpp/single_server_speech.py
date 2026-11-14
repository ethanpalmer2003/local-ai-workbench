"""Brief one-process Nemotron/Kokoro residency, alternation and concurrent-request screen."""

import base64
import hashlib
import json
import threading
import time
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from scripts.benchmarks.asr.shared.corpus import prepare_corpus
from scripts.benchmarks.asr.shared.requests import multipart
from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.resident_http import ResidentHttp
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp.asr_turns import speech_config
from scripts.launchers.audiocpp.kokoro import audio_environment
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.media.audio import decode_audio, mono_resample
from scripts.tests.cases.asr.shared.latency import Client
from scripts.tests.cases.audiocpp.audiocpp_transport import AudioReader
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.resources import summarize_resources, watch_resources

PORT = 18991
TEXT = "Hello. Tell me about your day, and I will help you practice a natural conversation."


def inventory():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=10) as response:
        return json.load(response)


def assert_resident(value):
    models = {item["id"]: item for item in value.get("data", [])}
    if set(models) != {"benchmark-asr", cfg.LANGUAGE_PRACTICE.tts_model} or not all(
        item.get("loaded") is True for item in models.values()
    ):
        raise RuntimeError(f"Both requested models must remain loaded: {value}")


def tts(timing=None):
    from scripts.launchers.asr.shared.practice_models import speech_body

    body = speech_body(
        {
            "model": cfg.LANGUAGE_PRACTICE.tts_model,
            "input": TEXT,
            "stream": True,
            "stream_format": "audio",
            "response_format": "pcm",
            "speed": 1,
            "options": {"seed": 42},
        }
    )
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/audio/speech", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    reader = AudioReader("audio", 24000)
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.headers.get_content_type() not in ("audio/pcm", "application/octet-stream", "audio/x-pcm"):
            raise ValueError(f"Expected raw PCM, got {response.headers}")
        while chunk := response.read1(8192):
            if reader.feed(chunk) and timing:
                timing.mark("first_audio")
    reader.finish()
    return bytes(reader.pcm)


def execute(kind, timer, server, upload, barrier=None) -> tuple[dict[str, Any], Any]:
    if barrier:
        barrier.wait(timeout=10)
    started = time.perf_counter()
    with timer.request() as timing:
        if kind == "asr":
            value = server.post("/v1/audio/transcriptions", *upload)
            if not isinstance(value.get("text"), str) or not value["text"].strip():
                raise ValueError("Empty ASR transcript")
        else:
            value = tts(timing)
    return {"kind": kind, **timing.record(), "client_started": started, "client_finished": time.perf_counter()}, value


def save_audio(run, label, data):
    destination = run.artifacts / f"{label}.wav"
    with wave.open(str(destination), "wb") as output:
        output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        output.writeframes(data)
    return {"file": str(destination), "audio_seconds": len(data) / 48000, "sha256": hashlib.sha256(data).hexdigest()}


def paced_overlap(run, server, parent_timer, clip, upload):
    samples, rate = decode_audio(clip["file"])
    pcm = (mono_resample(samples, rate).clip(-1, 1) * 32767).astype("<i2").tobytes()
    command = {
        "protocol": "audio",
        "url": f"http://127.0.0.1:{PORT}/v1/audio/transcriptions/live?model=benchmark-asr&sample_rate=16000&channels=1&sample_format=s16le&language=en-US",
        "rate": 16000,
        "pcm": base64.b64encode(pcm).decode(),
        "speech_bytes": len(pcm),
        "chunk_ms": 160,
        "automatic": False,
        "paced": True,
    }
    client = Client(run)
    stream_timer = BenchmarkLifecycle(
        lambda: server.identity() + f":{client.process.pid}" if server.identity() and client.process else "",
        client.stop,
    )
    with stream_timer:
        stream_timer.prepare(client.start)
        stream_timer.warmup(lambda: client.replay({**command, "paced": False}))
        barrier = threading.Barrier(2)

        def recognize():
            barrier.wait(timeout=10)
            with stream_timer.request() as timing:
                value = client.replay(command, timing)
            return {
                "kind": "paced_asr",
                "text": value["text"],
                **timing.record(),
                "first_partial_seconds": timing.marks["first_text"] - timing.marks["audio_start"],
                "final_after_audio_end_seconds": timing.marks["final_text"] - timing.marks["audio_end"],
            }

        def speak():
            barrier.wait(timeout=10)
            time.sleep(0.9)
            row, data = execute("tts", parent_timer.fork(), server, upload)
            row.update(save_audio(run, "during-paced-asr", data), start_delay_seconds=0.9)
            return row

        with ThreadPoolExecutor(max_workers=2) as pool:
            asr, speech = pool.submit(recognize), pool.submit(speak)
            result = [asr.result(timeout=30), speech.result(timeout=30)]
    return {"requests": result, "benchmark": stream_timer.record()}


def exercise(run, server, upload, report, memory):
    samples, stop = [], threading.Event()
    watcher = None
    try:
        with server.lifecycle as timer:
            timer.prepare(server.start, combined=True)
            models = {str(item["task"]): Path(item["path"]) for item in report["config"]["models"]}
            report["provenance"] = provenance.block(
                subject="audiocpp/single_server_speech",
                config=report["config"],
                frameworks=[provenance.framework_state("audiocpp")],
                models=[provenance.file_identity(label, path) for label, path in models.items()],
            )
            assert server.process is not None
            memory.watch_backend("audio", [server.process.pid])
            watcher = threading.Thread(
                target=watch_resources,
                args=(server.process, stop, samples, time.monotonic() + 180, lambda: memory.stage),
                daemon=True,
            )
            watcher.start()
            report["pid"] = server.process.pid
            report["inventories"].append(inventory())
            assert_resident(report["inventories"][-1])
            memory.stage = "warmup"
            timer.warmup(lambda: (server.post("/v1/audio/transcriptions", *upload), tts()))
            for index, kind in enumerate(("asr", "tts", "asr", "tts")):
                memory.stage = "alternating"
                row, value = execute(kind, timer, server, upload)
                row["stage"] = "alternating"
                if kind == "tts":
                    row.update(save_audio(run, f"alternating-{index}", value))
                else:
                    row["text"] = value["text"]
                report["requests"].append(row)
                report["inventories"].append(inventory())
                assert_resident(report["inventories"][-1])
            memory.stage = "concurrent"
            barrier = threading.Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(execute, kind, timer.fork(), server, upload, barrier) for kind in ("asr", "tts")]
                concurrent = []
                for future in futures:
                    row, value = future.result(timeout=70)
                    row["stage"] = "concurrent"
                    if row["kind"] == "tts":
                        row.update(save_audio(run, "concurrent", value))
                    else:
                        row["text"] = value["text"]
                    report["requests"].append(row)
                    concurrent.append(row)
            report["client_interval_overlap_seconds"] = max(
                0, min(r["client_finished"] for r in concurrent) - max(r["client_started"] for r in concurrent)
            )
            report["inventories"].append(inventory())
            assert_resident(report["inventories"][-1])
            report["identity_unchanged"] = timer.identity() == timer.prepared_identity
            memory.stage = "paced_overlap"
            report["paced_overlap"] = paced_overlap(run, server, timer, report["clip"], upload)
            report["inventories"].append(inventory())
            assert_resident(report["inventories"][-1])
            memory.stage = "resident_after_requests"
            time.sleep(1)
            report["status"] = "completed"
    finally:
        stop.set()
        if watcher:
            watcher.join(timeout=3)
        report["resources"] = summarize_resources(samples)
        report["benchmark"] = server.lifecycle.record()


def main():
    context = dict(require_native_execution("Single AudioCpp ASR/Kokoro screen"))
    run = CasePaths(__file__).new_run()
    clip = prepare_corpus(run, None)[0]
    config = speech_config(PORT)
    path = run.temp / "asr-kokoro.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    hashes = {}
    for model in config["models"]:
        with open(model["path"], "rb") as source:
            hashes[model["id"]] = hashlib.file_digest(source, "sha256").hexdigest()
    command = [str(project_cfg.AUDIOCPP_SERVER_EXE), "--config", str(path), "--port", str(PORT), "--no-ui"]
    server = ResidentHttp(
        command, PORT, run.logs / "server.log", model_identity=json.dumps(hashes), env=audio_environment()
    )
    report: dict[str, Any] = {
        "status": "running",
        "execution_context": context,
        "config": config,
        "command": command,
        "model_sha256": hashes,
        "clip": clip,
        "requests": [],
        "inventories": [],
        "limits": "One process, standard runtime/global Vulkan; concurrent client intervals do not prove parallel GPU kernels. No Gemma, microphone, physical playback or multilingual quality test. Loaded-state snapshots do not expose hidden reload counters.",
    }
    print(f"[OUTPUT] {run.root}", flush=True)
    try:
        with BenchmarkVram(run, context) as memory:
            exercise(run, server, multipart(Path(clip["file"]).read_bytes(), model="benchmark-asr"), report, memory)
    except Exception as error:
        report.update(status="failed", error=str(error))
    finally:
        (run.artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key in ("status", "error", "identity_unchanged", "client_interval_overlap_seconds", "requests")
            }
        ),
        flush=True,
    )
    return int(report["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
