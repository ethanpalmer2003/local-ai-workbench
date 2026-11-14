"""Matched SSE/raw-PCM measurements; starts only missing audio services when requested."""

import argparse
import base64
import hashlib
import json
import statistics
import time
import urllib.request
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.launchers import launcher_config as cfg
from scripts.shared.backends import backend_sessions
from scripts.shared.service_identity import audio_identity
from scripts.tests.cases.audiocpp.audiocpp_streaming import buffer_metrics
from scripts.tests.shared.paths import CasePaths


@dataclass
class AudioReader:
    transport: str
    rate: int
    pending: bytes = b""
    pcm: bytearray = field(default_factory=bytearray)
    complete: bool = False

    def feed(self, chunk: bytes) -> int:
        before = len(self.pcm) // 2 * 2
        if self.transport == "audio":
            self.pcm.extend(chunk)
            return len(self.pcm) // 2 * 2 - before
        self.pending += chunk
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            self.event(line)
        return len(self.pcm) // 2 * 2 - before

    def event(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        data = line[5:].strip()
        if data == b"[DONE]":
            self.complete = True
            return
        event = json.loads(data)
        if event.get("error") or event.get("type") == "error":
            raise RuntimeError(event)
        if event.get("type") == "speech.audio.delta":
            self.pcm.extend(base64.b64decode(event["audio"], validate=True))

    def finish(self) -> None:
        if self.transport == "sse" and self.pending.strip():
            self.event(self.pending)
        if self.transport == "sse" and not self.complete:
            raise RuntimeError("SSE stream missing completion marker")
        if not self.pcm or len(self.pcm) % 2:
            raise RuntimeError("Empty audio or incomplete PCM sample")
        if self.pcm[:4] == b"RIFF":
            raise RuntimeError("Expected headerless PCM; server returned WAV")


def measure(transport: str, text: str, seed: int, timeout: float, path: Path) -> dict[str, Any]:
    payload = {
        "model": cfg.AUDIOCPP_SERVICE.model,
        "voice": cfg.AUDIOCPP_SERVICE.voice,
        "input": text,
        "stream": True,
        "response_format": "pcm",
        "stream_format": transport,
        "options": {"seed": str(seed)},
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/v1/audio/speech",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    reader = AudioReader(transport, cfg.AUDIOCPP_SERVICE.streaming.pcm_sample_rate)
    started = time.perf_counter()
    trace = []
    body_bytes = 0
    decode_cpu = 0.0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        expected = (
            ("text/event-stream",) if transport == "sse" else ("audio/pcm", "application/octet-stream", "audio/x-pcm")
        )
        if content_type not in expected:
            raise RuntimeError(
                f"Requested {transport}, received {content_type}; comparison requires both native formats"
            )
        headers_time = time.perf_counter() - started
        while chunk := response.read1(8192):
            body_bytes += len(chunk)
            cpu = time.thread_time()
            added = reader.feed(chunk)
            decode_cpu += time.thread_time() - cpu
            if added:
                trace.append({"arrival": time.perf_counter() - started, "duration": added / (reader.rate * 2)})
    reader.finish()
    elapsed = time.perf_counter() - started
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, reader.rate, 0, "NONE", "not compressed"))
        wav.writeframes(reader.pcm)
    consumed = required = 0.0
    for chunk in trace:
        required = max(required, chunk["arrival"] - trace[0]["arrival"] - consumed)
        consumed += chunk["duration"]
    return {
        "transport": transport,
        "request": payload,
        "first_audio_s": trace[0]["arrival"],
        "headers_s": headers_time,
        "elapsed_s": elapsed,
        "audio_s": consumed,
        "rtf": elapsed / consumed,
        "body_bytes": body_bytes,
        "pcm_bytes": len(reader.pcm),
        "body_to_pcm_ratio": body_bytes / len(reader.pcm),
        "decode_cpu_ms": decode_cpu * 1000 if decode_cpu else None,
        "required_buffer_s": required + 0.03,
        "pcm_sha256": hashlib.sha256(reader.pcm).hexdigest(),
        "arrivals": trace,
        "buffers": {str(b): buffer_metrics(trace, b) for b in (0.05, 0.3, 0.5, 1, 2)},
    }


def summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for transport in ("sse", "audio"):
        samples = [r for r in results if r["transport"] == transport]
        if not samples:
            continue
        row = {"transport": transport, "samples": len(samples)}
        for metric in ("first_audio_s", "elapsed_s", "rtf", "body_to_pcm_ratio", "required_buffer_s"):
            row[metric] = statistics.median(r[metric] for r in samples)
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-backends", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--budget-seconds", type=float, default=150)
    parser.add_argument("--request-timeout", type=float, default=25)
    args = parser.parse_args()
    if args.repeats < 1 or args.budget_seconds <= 0 or args.request_timeout <= 0:
        parser.error("repeats and time limits must be positive")
    run = CasePaths(__file__).new_run()
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    report: dict[str, Any] = {"name": "audio.cpp SSE versus raw PCM", "category": "probes", "status": "failed"}
    print(run.root, flush=True)
    try:
        with backend_sessions(run, ("audio",), args.start_backends) as memory:
            lifecycle = BenchmarkLifecycle(audio_identity)
            lifecycle.adopt_prepared(time.perf_counter() - started, acquisition=True)
            report["setup_boundary"] = (
                "Backend session acquisition including monitor setup; reused services have no observable original load time"
            )
            url = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/proxy/config"
            with urllib.request.urlopen(url, timeout=5) as response:
                (run.artifacts / "defaults.json").write_bytes(response.read())
            memory.stage = "warmup"
            for transport in ("sse", "audio"):
                lifecycle.warmup(
                    lambda: measure(
                        transport, "A short warmup.", 0, args.request_timeout, run.artifacts / f"warmup-{transport}.wav"
                    ),
                    includes_model_load=transport == "sse",
                )
            deadline = time.perf_counter() + args.budget_seconds
            text = "Hello there. This is a streaming speech comparison. We can take our time and listen carefully to the whole sentence."
            for repeat in range(args.repeats):
                if time.perf_counter() + 2 * args.request_timeout > deadline:
                    break
                for transport in ("sse", "audio") if repeat % 2 == 0 else ("audio", "sse"):
                    memory.stage = f"{transport}-{repeat}"
                    result, timing = lifecycle.measure(
                        lambda: measure(
                            transport,
                            text,
                            1234 + repeat,
                            args.request_timeout,
                            run.artifacts / f"{repeat}-{transport}.wav",
                        ),
                        accept=lambda value: not value.get("error"),
                    )
                    result.update(timing)
                    result["repeat"] = repeat
                    results.append(result)
                    (run.artifacts / "samples.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
                    print(
                        json.dumps({k: v for k, v in result.items() if k not in ("arrivals", "buffers", "request")}),
                        flush=True,
                    )
            report.update(
                status="completed" if len(results) == args.repeats * 2 else "incomplete", summary=summary(results)
            )
            report["benchmark"] = lifecycle.record()
    except BaseException as error:
        report["error"] = str(error)
        raise
    finally:
        report.update(
            total_seconds=time.perf_counter() - started,
            samples=len(results),
            streaming=asdict(cfg.AUDIOCPP_SERVICE.streaming),
            reasoning="not applicable",
            limitations="Standalone TTS only. Body bytes exclude HTTP headers/framing. Python reader CPU is not browser CPU; null CPU time is below timer resolution. Buffer estimates simulate arrivals, not actual playback. Same text/seed does not guarantee deterministic GPU output; inspect PCM hashes and durations. No browser listening test.",
        )
        pairs = [[r for r in results if r["repeat"] == i] for i in range(args.repeats)]
        report["matched_pairs"] = [
            {"repeat": pair[0]["repeat"], "identical_pcm": pair[0]["pcm_sha256"] == pair[1]["pcm_sha256"]}
            for pair in pairs
            if len(pair) == 2
        ]
        run.write_report(report)
        lines = [
            "",
            "| Transport | Samples | Median first audio (s) | Median total (s) | Body / PCM bytes | Median simulated buffer (s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in report.get("summary", []):
            lines.append(
                f"| {row['transport']} | {row['samples']} | {row['first_audio_s']:.3f} | {row['elapsed_s']:.3f} | {row['body_to_pcm_ratio']:.3f} | {row['required_buffer_s']:.3f} |"
            )
        lines.extend(["", report["limitations"]])
        with (run.artifacts / "report.md").open("a", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
