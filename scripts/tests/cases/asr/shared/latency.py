"""Brief paced ASR screen: incremental text and explicit/automatic end-of-turn delay."""

import argparse
import base64
import hashlib
import json
import queue
import subprocess
import threading
from typing import Any, TextIO

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.resident_http import ResidentHttp
from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared.file_cli import environment
from scripts.launchers.asr.shared.resident_profiles import audio_config, profiles
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.media.audio import decode_audio, mono_resample
from scripts.launchers.shared.services.process import stop_owned
from scripts.tests.cases.asr.shared.corpus import prepare_corpus
from scripts.tests.shared.paths import CasePaths


class Client:
    def __init__(self, run):
        self.run, self.process = run, None
        self.log: TextIO | None = None
        self.reader: threading.Thread | None = None
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()

    def start(self):
        self.log = (self.run.logs / "transport.log").open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            [cfg.PI_CLIENT.node_cmd, str(project_cfg.TEST_CASES_DIR / "asr/shared/paced_client.mjs")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            encoding="utf-8",
        )
        launch_util.assign_process_to_job(self.process.pid)
        source = self.process.stdout
        assert source is not None

        def read():
            for line in source:
                self.messages.put(json.loads(line))

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        if self.messages.get(timeout=10).get("kind") != "ready":
            raise RuntimeError("Transport did not become ready")

    def replay(self, command, timing=None):  # noqa: C901
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps(command) + "\n")
        self.process.stdin.flush()
        events, transcript = [], ""
        while True:
            item = self.messages.get(timeout=25)
            if item["kind"] == "failure":
                raise RuntimeError(item["error"])
            if item["kind"] == "complete":
                if not transcript.strip():
                    raise ValueError("No final transcript")
                return {"events": events, "text": transcript}
            events.append(item)
            if item["kind"] in ("audio_start", "audio_end") and timing:
                timing.mark(item["kind"])
            if item["kind"] != "asr_event":
                continue
            event = item["item"]
            kind = event.get("type", "")
            if kind == "error" or kind.endswith(".failed"):
                raise RuntimeError(str(event))
            text = event.get("delta") or event.get("text") or event.get("transcript") or ""
            if text.strip() and timing:
                timing.mark("first_text")
            if kind.endswith(".completed") or kind == "transcript.text.done":
                transcript = text
                if text.strip() and timing:
                    timing.mark("final_text")

    def stop(self):
        if self.process:
            stop_owned(self.process, timeout=5)
        if self.log is not None:
            self.log.close()


def configuration(engine, automatic, clip, run, port):
    cmd, model = profiles(port)[engine]
    protocol = {"audiocpp-vulkan": "audio", "nemo-speechcpp": "nemo", "speechcpp": "speech"}[engine]
    rate = 24000 if protocol == "speech" else 16000
    if protocol == "audio":
        path = run.temp / "audio.json"
        native = audio_config(engine)
        native["models"][0]["mode"] = "streaming"
        path.write_text(json.dumps(native), encoding="utf-8")
        cmd = [part.replace("{config}", str(path)) for part in cmd]
    if protocol == "speech" and automatic:
        cmd.insert(3, str(model_cfg.path("asr/speechcpp/silero-vad")))
    audio, source_rate = decode_audio(clip["file"])
    pcm = (mono_resample(audio, source_rate, target_rate=rate).clip(-1, 1) * 32767).astype("<i2").tobytes()
    speech_bytes = len(pcm)
    if automatic:
        pcm += bytes(round(rate * 1.2) * 2)
    routes = {
        "audio": f"http://127.0.0.1:{port}/v1/audio/transcriptions/live?model=benchmark-asr&sample_rate={rate}&channels=1&sample_format=s16le&language=en-US",
        "nemo": f"ws://127.0.0.1:{port}/v1/audio/transcriptions/realtime",
        "speech": f"ws://127.0.0.1:{port}/v1/realtime",
    }
    return (
        cmd,
        model,
        {
            "protocol": protocol,
            "url": routes[protocol],
            "rate": rate,
            "pcm": base64.b64encode(pcm).decode(),
            "speech_bytes": speech_bytes,
            "chunk_ms": 160,
            "automatic": automatic,
            "paced": True,
        },
    )


def latency_metrics(marks, duration, speech_end) -> dict[str, Any]:
    clip_delay = marks["final_text"] - marks["audio_end"]
    return {
        "first_text_seconds": marks["first_text"] - marks.get("audio_start", 0) if "first_text" in marks else None,
        "final_after_audio_end_seconds": clip_delay,
        "estimated_trailing_silence_seconds": duration - speech_end,
        "final_after_estimated_speech_end_seconds": clip_delay + duration - speech_end,
        "pacing_elapsed_seconds": marks["audio_end"] - marks.get("audio_start", 0),
    }


def screen(engine, automatic, clip, run, port):
    cmd, model, request = configuration(engine, automatic, clip, run, port)
    server = ResidentHttp(
        cmd,
        port,
        run.logs / f"{engine}-{automatic}.log",
        model_identity=str(model),
        env=environment(ASR_FILE_PROFILES[engine]),
    )
    client = Client(run)

    def start():
        server.start()
        client.start()

    def cleanup():
        try:
            client.stop()
        finally:
            server.stop()

    timer = BenchmarkLifecycle(
        lambda: server.identity() + f":{client.process.pid}" if server.identity() and client.process else "", cleanup
    )
    row: dict[str, Any] = {
        "engine": engine,
        "automatic_vad": automatic,
        "command": cmd,
        "model": str(model),
        "status": "running",
    }
    with model.open("rb") as source:
        row["model_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    try:
        with timer:
            timer.prepare(start, combined=engine != "audiocpp-vulkan")
            timer.warmup(lambda: client.replay({**request, "paced": False}), includes_model_load=True)
            with timer.request() as timing:
                result = client.replay(request, timing)
            row.update(result, timing=timing.record(), status="completed")
            marks = timing.marks
            import numpy as np

            samples, rate = decode_audio(clip["file"])
            audible = np.flatnonzero(np.abs(samples) > 0.01)
            speech_end = float(audible[-1] + 1) / rate if len(audible) else clip["duration_seconds"]
            row.update(latency_metrics(marks, clip["duration_seconds"], speech_end))
    except Exception as error:
        row.update(status="failed", error=str(error))
    row["benchmark"] = timer.record()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", nargs="+", choices=("audiocpp-vulkan", "nemo-speechcpp", "speechcpp"))
    args = parser.parse_args()
    context = dict(require_native_execution("Paced ASR latency screen"))
    run = CasePaths(__file__).new_run()
    clip = prepare_corpus(run, None)[0]
    report: dict[str, Any] = {
        "execution_context": context,
        "clip": clip,
        "results": [],
        "limits": "One paced replay after warmup; clip-end anchor includes original trailing silence. No microphone/browser/LLM/TTS. Parakeet prebuilt exposes no paced-input adapter.",
    }
    print(f"[OUTPUT] {run.root}", flush=True)
    for index, (engine, automatic) in enumerate(
        (("audiocpp-vulkan", False), ("nemo-speechcpp", False), ("speechcpp", False), ("speechcpp", True))
    ):
        if args.engines and engine not in args.engines:
            continue
        try:
            result = screen(engine, automatic, clip, run, 18981 + index)
        except Exception as error:
            result = {"engine": engine, "status": "failed", "error": str(error)}
        report["results"].append(result)
        (run.artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k
                    in (
                        "engine",
                        "status",
                        "error",
                        "first_text_seconds",
                        "final_after_audio_end_seconds",
                        "automatic_vad",
                    )
                }
            ),
            flush=True,
        )
    return int(any(row["status"] != "completed" for row in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
