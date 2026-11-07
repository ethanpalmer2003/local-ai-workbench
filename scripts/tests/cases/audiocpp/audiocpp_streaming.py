"""Compare Breeze streaming controls with fixed standalone text."""

import argparse
import base64
import http.client
import json
import statistics
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.launchers import launcher_config as cfg
from scripts.tests.shared.backends import backend_sessions
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.service_identity import audio_identity


def buffer_metrics(chunks: list[dict[str, float]], buffer: float) -> dict[str, float | int]:
    end = 0.0
    gaps = 0
    gap_seconds = 0.0
    for index, chunk in enumerate(chunks):
        arrival = chunk["arrival"]
        if index == 0:
            end = arrival + buffer + 0.02
        elif end < arrival + 0.01:
            gaps += 1
            gap_seconds += max(0.0, arrival - end)
            end = arrival + buffer + 0.02
        end += chunk["duration"]
    return {"underruns": gaps, "late_seconds": gap_seconds}


def write_summary(artifacts: Path, report: dict[str, Any]) -> None:
    (artifacts / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Breeze streaming comparison",
        "",
        report["conditions"],
        "",
        "| Profile | Samples | Median first data (s) | Largest simulated startup buffer (s) | Median generation/audio ratio |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in report["summary"]:
        lines.append(
            f"| {item['profile']} | {item['samples']} | {item['median_first_data_s']:.3f} | {item['max_required_buffer_s']:.3f} | {item['median_rtf']:.3f} |"
        )
    lines.extend(
        [
            "",
            "Unsupported profiles: " + ", ".join(report["unsupported_profiles"]),
            "",
            "First-data latency excludes the player buffer. Ratios above 1 mean generation took longer than the audio duration. Buffer estimates reproduce recorded chunk arrival timing; they do not guarantee future playback or score speech quality.",
        ]
    )
    for limitation in report.get("limitations", []):
        lines.extend(["", limitation])
    (artifacts / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def measure(text: str, options: dict[str, object], wav_path: Path, timeout: float = 60) -> dict[str, Any]:
    payload = {"input": text, "stream": True, "response_format": "pcm", "stream_format": "sse", "options": options}
    url = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/v1/audio/speech"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    chunks = []
    pcm = bytearray()
    complete = False
    stream_finished: float | None = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                complete = True
                stream_finished = time.perf_counter()
                break
            event = json.loads(data)
            if event.get("error") or event.get("type") == "error":
                return {"error": event, "elapsed": time.perf_counter() - started}
            if event.get("type") == "speech.audio.delta":
                chunk = base64.b64decode(event["audio"])
                chunks.append({"arrival": time.perf_counter() - started, "duration": len(chunk) / 48000})
                pcm.extend(chunk)
    if not complete or not chunks:
        raise RuntimeError("Incomplete or empty audio stream")
    assert stream_finished is not None
    with wave.open(str(wav_path), "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    duration = len(pcm) / 48000
    consumed = 0.0
    required = 0.0
    for chunk in chunks:
        required = max(required, chunk["arrival"] - chunks[0]["arrival"] - consumed)
        consumed += chunk["duration"]
    elapsed = stream_finished - started
    return {
        "elapsed": elapsed,
        "first_data": chunks[0]["arrival"],
        "audio_seconds": duration,
        "rtf": elapsed / duration,
        "minimum_buffer_seconds": required + 0.03,
        "chunks": chunks,
        "buffers": {
            str(buffer): buffer_metrics(chunks, buffer)
            for buffer in (0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--start-backends",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="start missing task-owned backends and stop them afterward",
    )
    parser.add_argument("--budget-seconds", type=float, default=240)
    parser.add_argument("--request-timeout", type=float, default=60)
    parser.add_argument("--profiles", nargs="+", help="run only named profiles")
    parser.add_argument("--texts", nargs="+", choices=("short", "long"), help="select text cases")
    args = parser.parse_args()
    run = CasePaths(__file__).new_run()
    setup_started = time.perf_counter()
    with backend_sessions(run, ("audio",), args.start_backends) as memory:
        run_comparison(args, run, memory, time.perf_counter() - setup_started)


def run_comparison(args: argparse.Namespace, run: RunPaths, memory: BenchmarkVram, setup_seconds: float) -> None:  # noqa: C901
    started = time.perf_counter()
    deadline = started + args.budget_seconds
    url = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/v1/models?include_params=true&include_session_options=true"
    with urllib.request.urlopen(url, timeout=10) as response:
        (run.artifacts / "server-models.json").write_bytes(response.read())
    memory.stage = "warmup"
    lifecycle = BenchmarkLifecycle(audio_identity)
    lifecycle.adopt_prepared(setup_seconds, acquisition=True)
    warmups = []
    lifecycle.warmup(
        lambda: warmups.append(
            measure("A short warmup.", {"seed": "0"}, run.artifacts / "warmup.wav", args.request_timeout)
        ),
        includes_model_load=True,
    )
    warmup = warmups[0]
    if "error" in warmup:
        raise RuntimeError(warmup["error"])
    profiles = {
        "installed-default": {},
        "frames-8": {"stream_frames_per_event": 8},
        "frames-16": {"stream_frames_per_event": 16},
        "frames-16-lookahead-0": {"stream_frames_per_event": 16, "stream_lookahead_margin": 0},
        "lookahead-0": {"stream_lookahead_margin": 0},
        "lookahead-12": {"stream_lookahead_margin": 12},
        "upstream-low-latency": {
            "stream_chunk_policy": "grow",
            "stream_frames_per_event": 16,
            "stream_lookahead_margin": 0,
        },
        "upstream-conservative": {
            "stream_chunk_policy": "fixed",
            "stream_frames_per_event": 16,
            "stream_lookahead_margin": 12,
        },
    }
    texts = {
        "short": "Hello there. This is a streaming speech test. How are you doing today?",
        "long": "Hello there, I am glad you made it back. We should take a moment to think this through before we move. There is no need to rush into anything. Tell me what you noticed outside, and then we can decide together what to do next.",
    }
    if args.profiles:
        profiles = {name: profiles[name] for name in args.profiles}
    if args.texts:
        texts = {name: texts[name] for name in args.texts}
    results = []
    unsupported = set()
    timed_out = False
    transport_failed = False
    # Alternate profile order to reduce warm-cache and temperature bias.
    for repeat in range(args.repeats):
        for text_name, text in texts.items():
            names = list(profiles) if repeat % 2 == 0 else list(reversed(profiles))
            for name in names:
                if name in unsupported:
                    continue
                if time.perf_counter() > deadline - (args.request_timeout + 5):
                    timed_out = True
                    break
                options: dict[str, object] = {"seed": str(1234 + repeat), **profiles[name]}
                memory.stage = f"{name}-{text_name}-{repeat}"
                result: dict[str, Any]
                try:
                    result, timing = lifecycle.measure(
                        lambda: measure(
                            text, options, run.artifacts / f"{name}-{text_name}-{repeat}.wav", args.request_timeout
                        ),
                        accept=lambda value: not value.get("error"),
                    )
                    result.update(timing)
                except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
                    result = {"error": str(error), "transport_failure": True}
                result.update(profile=name, text_case=text_name, repeat=repeat, options=options)
                results.append(result)
                if result.get("error"):
                    unsupported.add(name)
                (run.artifacts / "timings.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
                print(
                    json.dumps({key: value for key, value in result.items() if key not in ("chunks", "buffers")}),
                    flush=True,
                )
                if result.get("transport_failure"):
                    transport_failed = True
                    break
            if timed_out or transport_failed:
                break
        if timed_out or transport_failed:
            break
    summary = []
    for name in profiles:
        good = [result for result in results if result["profile"] == name and not result.get("error")]
        if good:
            summary.append(
                {
                    "profile": name,
                    "samples": len(good),
                    "median_first_data_s": statistics.median(result["first_data"] for result in good),
                    "max_required_buffer_s": max(result["minimum_buffer_seconds"] for result in good),
                    "median_rtf": statistics.median(result["rtf"] for result in good),
                }
            )
    report = {
        "benchmark": lifecycle.record(),
        "setup_boundary": "Backend session acquisition including monitor setup; original load time unavailable for reused services",
        "summary": summary,
        "unsupported_profiles": sorted(unsupported),
        "time_budget_reached": timed_out,
        "transport_failure": transport_failed,
        "elapsed": time.perf_counter() - started,
        "conditions": "Standalone TTS only; no LLM requests initiated. PCM assumed mono s16le 24 kHz. First-data excludes playback buffering. Buffer results are simulated from real arrivals. All profiles use the same text/seed for each matched comparison.",
    }
    write_summary(run.artifacts, report)
    print(json.dumps(report, indent=2))
    print(run.artifacts)


if __name__ == "__main__":
    main()
