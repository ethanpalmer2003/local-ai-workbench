"""Brief automatic Silero/Nemotron turns with one Kokoro/ASR server; no microphone."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.resident_http import ResidentHttp
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp.asr_turns import Turns, speech_config
from scripts.launchers.audiocpp.kokoro import audio_environment
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.media.audio import decode_audio, mono_resample
from scripts.tests.cases.asr.shared.corpus import prepare_corpus
from scripts.tests.cases.audiocpp import single_server_speech as shared
from scripts.tests.shared.paths import CasePaths


def replay(name, pcm, expected, run, server, speak=False):
    events = []
    turns = Turns(f"http://127.0.0.1:{shared.PORT}", run.logs / f"{name}-silero.log")
    timer = BenchmarkLifecycle(
        lambda: server.identity() + f":{turns.vad.process.pid}" if server.identity() and turns.vad.process else "",
        turns.close,
    )
    row = {"case": name, "expected_turns": expected, "status": "running"}
    try:
        with timer:
            timer.prepare(turns.start)
            timer.warmup(lambda: [turns.push(bytes(1024)) for _ in range(8)])
            initial_samples = turns.samples
            with ThreadPoolExecutor(max_workers=1) as pool, timer.request() as timing:
                started, future = time.perf_counter(), None
                for offset in range(0, len(pcm), 1024):
                    frame = pcm[offset : offset + 1024].ljust(1024, b"\0")
                    time.sleep(max(0, (offset + 1024) / 32000 - (time.perf_counter() - started)))
                    events.extend(turns.push(frame))
                    if speak and future is None and time.perf_counter() - started >= 1:
                        future = pool.submit(shared.tts)
                deadline = time.monotonic() + 3
                while (turns.pending or turns.active) and time.monotonic() < deadline:
                    events.extend(turns.poll())
                    time.sleep(0.01)
                completed = [item for item in events if item.get("type") == "transcript.text.done"]
                if len(completed) != expected or turns.active or turns.pending:
                    raise ValueError(
                        f"Expected {expected} silence-ended turns, got {len(completed)}; active={bool(turns.active)}"
                    )
                if any(item.get("end_reason") != "silence" or not item.get("text", "").strip() for item in completed):
                    raise ValueError("A turn was incomplete or did not end through VAD silence")
                if future:
                    row["kokoro"] = shared.save_audio(run, name + "-kokoro", future.result(timeout=15))
                for item in completed:
                    item["final_after_vad_speech_end_seconds"] = (
                        item["observed_at"] - started - (item["speech_end_sample"] - initial_samples) / 16000
                    )
            row.update(status="completed", turns=completed, timing=timing.record())
    except Exception as error:
        row.update(status="failed", error=str(error))
    row.update(events=events, benchmark=timer.record())
    return row


def main():
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", choices=("silence", "utterance", "short-pause"))
    args = parser.parse_args()

    context = dict(require_native_execution("AudioCpp Silero automatic turn checks"))
    run = CasePaths(__file__).new_run()
    clip = prepare_corpus(run, None)[0]
    audio, rate = decode_audio(clip["file"])
    audio = mono_resample(audio, rate)
    positions = np.flatnonzero(np.abs(audio) > 0.005)
    trimmed = audio[max(0, positions[0] - 960) : min(len(audio), positions[-1] + 960)]
    cases = [
        ("silence", np.zeros(16000, dtype=np.float32), 0, False),
        ("utterance", np.concatenate((audio, np.zeros(24000))), 1, True),
        ("short-pause", np.concatenate((trimmed, np.zeros(5600), trimmed, np.zeros(24000))), 1, False),
    ]
    config = speech_config(shared.PORT)
    path = run.temp / "asr-kokoro.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    server = ResidentHttp(
        [str(project_cfg.AUDIOCPP_SERVER_EXE), "--config", str(path), "--port", str(shared.PORT), "--no-ui"],
        shared.PORT,
        run.logs / "server.log",
        model_identity=json.dumps(config["models"]),
        env=audio_environment(),
    )
    report: dict[str, Any] = {
        "execution_context": context,
        "settings": {**asdict(cfg.AUDIOCPP_VAD), "model": str(cfg.AUDIOCPP_VAD.model)},
        "config": config,
        "clip": clip,
        "results": [],
        "status": "running",
        "limits": "Paced saved English; CPU native VAD helper plus one Vulkan ASR/TTS server. No microphone/browser/echo handling. No Gemma workload.",
    }
    print(f"[OUTPUT] {run.root}", flush=True)
    try:
        with server.lifecycle as lifecycle:
            lifecycle.prepare(server.start, combined=True)
            lifecycle.warmup(shared.tts)
            for name, samples, expected, speak in cases:
                if args.cases and name not in args.cases:
                    continue
                pcm = (samples.clip(-1, 1) * 32767).astype("<i2").tobytes()
                result = replay(name, pcm, expected, run, server, speak)
                report["results"].append(result)
                print(
                    json.dumps({k: v for k, v in result.items() if k in ("case", "status", "error", "turns")}),
                    flush=True,
                )
                (run.artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            report["inventory"] = shared.inventory()
            shared.assert_resident(report["inventory"])
        report["status"] = "completed" if all(row["status"] == "completed" for row in report["results"]) else "failed"
    except Exception as error:
        report.update(status="failed", error=str(error))
    finally:
        report["server_benchmark"] = server.lifecycle.record()
        (run.artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return int(report["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
