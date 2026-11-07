"""Opt-in saved-PCM practice gateway smoke; no microphone hardware or browser access."""

import argparse
import json
import threading
import time
import urllib.request
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector, server
from scripts.launchers.audiocpp import asr
from scripts.launchers.koboldcpp import kobold, kobold_lite
from scripts.launchers.llamacpp.language_practice import chat_command, start_tts
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.media.audio import decode_audio, mono_resample
from scripts.launchers.shared.services import native
from scripts.launchers.shared.services.process import http_ready, stop_owned
from scripts.tests.cases.asr.shared.corpus import default_corpus
from scripts.tests.shared.native_suites import refuse_existing_sessions
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.resources import monitor_process


def post(base, path, body, binary=False):
    data = body if binary else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path, data, {"Content-Type": "application/octet-stream" if binary else "application/json"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read()
        return data if path == "/v1/audio/speech" else json.loads(data)


def exercise(runtime, pcm, report, engine=cfg.AsrStartupEngine.AUDIOCPP):
    chat_port, proxy_port = 19194, 19195
    process, gateway, thread = None, None, None
    token = None
    base = f"http://127.0.0.1:{proxy_port}"
    errors = []

    def on_server(value):
        nonlocal gateway
        gateway = value

    def run_gateway():
        try:
            if runtime == "llamacpp":
                server.run_proxy(
                    engine,
                    "127.0.0.1",
                    proxy_port,
                    f"http://127.0.0.1:{chat_port}",
                    asr.url()
                    if engine == cfg.AsrStartupEngine.AUDIOCPP
                    else f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}",
                    on_server,
                )
            else:
                kobold_lite.run_proxy(on_server=on_server)
        except Exception as error:
            errors.append(str(error))

    def cleanup():
        if gateway:
            gateway.shutdown()
        if thread:
            thread.join(timeout=10)
        if process:
            stop_owned(process)

    def setup():
        nonlocal process, thread
        if launch_util.port_listening(proxy_port):
            raise RuntimeError("Smoke gateway port occupied; no session stopped")
        if runtime == "llamacpp":
            launch_util.llama_server_running()  # Required existing-session discovery; never stop it.
            command = chat_command()
            files = (cfg.GEMMA_AUDIO_ASR.exe, cfg.GEMMA_AUDIO_ASR.model)
        else:
            command = kobold.server_command("shared")
            files = (cfg.KOBOLDCPP_SERVICE.exe, cfg.GEMMA_AUDIO_ASR.model)
        command[command.index("--port") + 1] = str(chat_port)
        process = native.start_server(
            command,
            files,
            chat_port,
            f"Practice {runtime} smoke",
            lambda: http_ready(
                f"http://127.0.0.1:{chat_port}" + ("/health" if runtime == "llamacpp" else "/api/extra/version")
            ),
            lambda: native.matches(command),
            component_key=runtime,
        )
        thread = threading.Thread(target=run_gateway, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not http_ready(base + "/health"):
            if errors or time.monotonic() > deadline:
                raise RuntimeError(str(errors) or "Practice gateway did not start")
            time.sleep(0.05)

    timer = BenchmarkLifecycle(lambda: str(process.pid) if process else "reused-matching-server", cleanup)

    def start_vad():
        nonlocal token
        token = post(base, "/asr/live/start", {"language": "en"})["session"]

    vad_timer = BenchmarkLifecycle(
        lambda: token or "", lambda: post(base, f"/asr/live/{token}/stop", b"", True) if token else None
    )
    try:
        with timer, vad_timer:
            timer.prepare(setup, combined=True)
            timer.warmup(lambda: http_ready(base + "/health"))
            vad_timer.prepare(start_vad, combined=True)
            vad_timer.warmup(lambda: post(base, f"/asr/live/{token}/audio", bytes(1024), True))
            events = []
            with timer.request() as timing:
                started = time.perf_counter()
                for offset in range(0, len(pcm), 4096):
                    block = pcm[offset : offset + 4096]
                    time.sleep(max(0, (offset + len(block)) / 32000 - (time.perf_counter() - started)))
                    events.extend(post(base, f"/asr/live/{token}/audio", block, True)["events"])
                for _ in range(100):
                    if any(event.get("type") == "transcript.text.done" for event in events):
                        break
                    events.extend(post(base, f"/asr/live/{token}/audio", b"", True)["events"])
                    time.sleep(0.03)
                finals = [event for event in events if event.get("type") == "transcript.text.done"]
                if len(finals) != 1 or not finals[0].get("text"):
                    raise RuntimeError(f"Expected one complete automatic transcript: {events}")
                reply = post(
                    base,
                    "/v1/chat/completions",
                    {
                        "messages": [
                            {"role": "user", "content": finals[0]["text"] + " Reply in one short English sentence."}
                        ],
                        "max_tokens": 192,
                        "stream": False,
                        "reasoning_effort": "none",
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                text = reply["choices"][0]["message"]["content"]
                if not text or not text.strip():
                    raise RuntimeError(f"Gemma returned no spoken content: {reply}")
                audio = post(
                    base,
                    "/v1/audio/speech",
                    {"input": text, "voice": "af_heart", "response_format": "wav", "stream": False},
                )
                if not text or audio[:4] != b"RIFF":
                    raise RuntimeError("Empty chat reply or invalid Kokoro WAV")
            report.update(
                status="completed",
                transcript=finals[0]["text"],
                reply=text,
                wav_bytes=len(audio),
                timing=timing.record(),
                first_partial_seconds=next(
                    (
                        item["observed_at"] - started
                        for item in events
                        if item.get("type") in ("transcript.text.delta", "transcript.text.snapshot")
                        and (item.get("delta") or item.get("text"))
                    ),
                    None,
                ),
                final_event=finals[0],
                final_after_vad_end_seconds=finals[0]["observed_at"]
                - started
                - (finals[0]["speech_end_sample"] - 512) / 16000,
            )
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["benchmark"] = timer.record()
        report["vad_benchmark"] = vad_timer.record()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtimes", nargs="+", choices=("llamacpp", "koboldcpp"), default=("llamacpp", "koboldcpp"))
    parser.add_argument(
        "--engine",
        choices=(
            "audiocpp-nemotron",
            "nemo-nemotron",
            "parakeetcpp-nemotron-cpu",
            "speechcpp-qwen-0.6b",
            "whisper-vulkan",
            "parakeetcpp-v3",
        ),
        default="audiocpp-nemotron",
    )
    parser.add_argument("--resources", action="store_true", help="Sample ASR process CPU/RSS and GPU memory")
    args = parser.parse_args()
    engine = cfg.AsrStartupEngine(args.engine)
    context = require_native_execution("Practice gateway smoke")
    refuse_existing_sessions([19193, 19194, 19195, 19196])
    run = CasePaths(__file__).new_run()
    report: dict[str, Any] = {
        "execution_context": context,
        "scope": "Saved PCM through both gateways; no browser microphone/echo/quality evaluation",
        "runtimes": {},
        "engine": args.engine,
    }
    samples, rate = decode_audio(Path(default_corpus()[0]["file"]))
    pcm = (mono_resample(samples, rate).clip(-1, 1) * 32767).astype("<i2").tobytes()
    pcm += bytes(64000)
    pcm = pcm.ljust((len(pcm) + 1023) // 1024 * 1024, b"\0")
    process = None
    started = time.perf_counter()

    def start_speech():
        nonlocal process
        process = asr.start() if engine == cfg.AsrStartupEngine.AUDIOCPP else start_tts()

    speech_timer = BenchmarkLifecycle(
        lambda: str(process.pid) if process else "reused-matching-server",
        lambda: stop_owned(process) if process else None,
    )
    asr_process = None

    def start_asr():
        nonlocal asr_process
        asr_process = selector.backend(engine).start()

    asr_timer = BenchmarkLifecycle(
        lambda: str(asr_process.pid) if asr_process else "shared-or-reused",
        lambda: stop_owned(asr_process) if asr_process else None,
    )
    try:
        with (
            speech_timer,
            asr_timer,
            patch.object(cfg.PARAKEETCPP_STREAM_ASR, "port", 19196),
            patch.object(cfg.NEMO_SPEECHCPP_ASR, "port", 19196),
            patch.object(cfg.SPEECHCPP_ASR, "port", 19196),
            patch.object(cfg.PARAKEETCPP_V3_ASR, "port", 19196),
            patch.object(cfg.WHISPERCPP_ASR, "port", 19196),
            patch.object(cfg.AUDIOCPP_SERVICE, "internal_port", 19193),
            patch.object(cfg, "AUDIOCPP_VAD", replace(cfg.AUDIOCPP_VAD, server_port=19193)),
            patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", engine),
            patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", cfg.KoboldcppSpeechStartupEngine.KOKORO_AUDIOCPP),
            patch.object(cfg.KOBOLDCPP_SERVICE, "model", "llamacpp/gemma-4-E4B-it-Q4_0"),
            patch.dict(cfg.KOBOLDCPP_KCPPS_ARGS, port=19194, port_param=19194),
            patch.object(cfg.KOBOLDCPP_SERVICE, "streaming_ui_port", 19195),
        ):
            speech_timer.prepare(start_speech, combined=True)
            speech_url = (
                asr.url()
                if engine == cfg.AsrStartupEngine.AUDIOCPP
                else f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}"
            )
            speech_timer.warmup(
                lambda: post(
                    speech_url,
                    "/v1/audio/speech",
                    {
                        "model": cfg.LANGUAGE_PRACTICE.tts_model,
                        "input": "Hello.",
                        "voice": "af_heart",
                        "response_format": "wav",
                        "stream": False,
                    },
                )
            )
            if engine != cfg.AsrStartupEngine.AUDIOCPP:
                asr_timer.prepare(start_asr, combined=True)
            from scripts.launchers.shared.transport.multipart import audio_upload

            upload = audio_upload(
                Path(default_corpus()[0]["file"]).read_bytes(), {"language": "en", "response_format": "json"}
            )
            recognizer_timer = speech_timer if engine == cfg.AsrStartupEngine.AUDIOCPP else asr_timer
            recognizer_timer.warmup(lambda: selector.backend(engine).transcribe(*upload))
            target = asr_process or process
            module = (
                "scripts.launchers.asr.parakeetcpp.streaming_server"
                if engine == cfg.AsrStartupEngine.PARAKEET_STREAM
                else None
            )
            monitor = (
                monitor_process(target, run.logs / "asr-vram.jsonl", worker_module=module)
                if args.resources and target
                else nullcontext({})
            )
            with monitor as resources:
                for runtime in args.runtimes:
                    row = report["runtimes"][runtime] = {}
                    exercise(runtime, pcm, row, engine)
            report["asr_resources"] = resources
    finally:
        report.update(
            name="Practice gateway smoke",
            category="asr",
            total_seconds=time.perf_counter() - started,
            status="completed"
            if len(report["runtimes"]) == len(args.runtimes)
            and all(row.get("status") == "completed" for row in report["runtimes"].values())
            else "failed",
            speech_benchmark=speech_timer.record(),
            asr_benchmark=asr_timer.record(),
        )
        run.write_report(report)
        print(run.artifacts / "report.json")


if __name__ == "__main__":
    main()
