"""Opt-in saved-PCM practice gateway smoke; no microphone hardware or browser access."""

import argparse
import base64
import json
import subprocess
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import requests

from scripts.benchmarks.asr.corpus import default_corpus
from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector, server
from scripts.launchers.asr.shared import practice_models
from scripts.launchers.audiocpp import asr
from scripts.launchers.koboldcpp import kobold, kobold_lite
from scripts.launchers.llamacpp.language_practice import chat_command, start_tts
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.media.audio import decode_audio, mono_resample, pcm_wav
from scripts.launchers.shared.services import native
from scripts.launchers.shared.services.process import stop_owned
from scripts.shared.resources import monitor_process
from scripts.shared.wait import http_ready
from scripts.tests.shared.native_suites import refuse_existing_sessions
from scripts.tests.shared.paths import CasePaths

# - The installed component that owns each startup engine's files; the launcher catalog stays the path owner
ENGINE_COMPONENTS = {
    cfg.AsrStartupEngine.AUDIOCPP: "audiocpp",
    cfg.AsrStartupEngine.QWEN3_AUDIOCPP: "audiocpp",
    cfg.AsrStartupEngine.COHERE: "audiocpp",
    cfg.AsrStartupEngine.NEMO: "asr/nemo-speechcpp",
    cfg.AsrStartupEngine.PARAKEET_STREAM: "asr/parakeetcpp",
    cfg.AsrStartupEngine.PARAKEET_V3: "asr/parakeetcpp",
    cfg.AsrStartupEngine.SPEECHCPP: "asr/speechcpp",
    cfg.AsrStartupEngine.WHISPER_VULKAN: "asr/whispercpp",
    cfg.AsrStartupEngine.QWEN3_ASR: "llamacpp",
    cfg.AsrStartupEngine.GEMMA_AUDIO: "llamacpp",
    cfg.AsrStartupEngine.GRANITE: "llamacpp",
    cfg.AsrStartupEngine.GEMMA_KOBOLD: "koboldcpp",
    cfg.AsrStartupEngine.EMBEDDED: "koboldcpp",
}


def post(base: str, path: str, body: dict[str, Any] | bytes, binary: bool = False) -> Any:
    data = body if binary else json.dumps(body).encode()
    response = requests.post(
        base + path,
        data=data,
        headers={"Content-Type": "application/octet-stream" if binary else "application/json"},
        timeout=45,
    )
    response.raise_for_status()
    return response.content if path == "/v1/audio/speech" else response.json()


# - The page's default Silero setting: a whole-turn recognizer always waits this long for the turn to end.
WHOLE_TURN_SILENCE_MS = 700


def whole_turn_body(wav: bytes, language: str = "en") -> bytes:
    """Kobold's own Whisper takes one base64 WAV per completed turn."""
    return json.dumps({"audio_data": base64.b64encode(wav).decode(), "langcode": language}).encode()


def final_after_speech_end(decode_seconds: float, silence_ms: int = WHOLE_TURN_SILENCE_MS) -> float:
    """Whole-turn latency from speech end: the silence the VAD waits for, then the upload it decodes."""
    return silence_ms / 1000 + decode_seconds


def engine_model(engine: cfg.AsrStartupEngine) -> Path:
    """The weights a startup engine loads; Kobold's built-in Whisper has no selector entry of its own."""
    if engine is cfg.AsrStartupEngine.EMBEDDED:
        return Path(str(cfg.KOBOLDCPP_KCPPS_ARGS["whispermodel"]))
    return selector.model(engine)


def _gateway_thread(runtime, engine, proxy_port, chat_port, on_server, errors) -> threading.Thread:
    def run_gateway():
        try:
            if runtime == "llamacpp":
                server.run_proxy(
                    engine,
                    "127.0.0.1",
                    proxy_port,
                    f"http://127.0.0.1:{chat_port}",
                    asr.url()
                    if engine in cfg.AUDIOCPP_ASR_ENGINES
                    else f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}",
                    on_server,
                )
            else:
                kobold_lite.run_proxy(on_server=on_server)
        except Exception as error:
            errors.append(str(error))

    thread = threading.Thread(target=run_gateway, daemon=True)
    thread.start()
    return thread


def _start_chat(runtime, chat_port):
    if runtime == "llamacpp":
        launch_util.llama_server_running()  # Required existing-session discovery; never stop it.
        command = chat_command()
        files = (cfg.GEMMA_AUDIO_ASR.exe, cfg.GEMMA_AUDIO_ASR.model)
    else:
        command = kobold.server_command("shared")
        files = (cfg.KOBOLDCPP_SERVICE.exe, cfg.GEMMA_AUDIO_ASR.model)
    command[command.index("--port") + 1] = str(chat_port)
    return native.start_server(
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


def _await_gateway(base, errors):
    from scripts.shared.wait import wait_ready

    wait_ready(
        lambda: http_ready(base + "/health"),
        10,
        label="practice gateway",
        interval=0.05,
        fail=lambda: str(errors) if errors else None,
    )


def _stream_pcm(base, token, pcm):
    events = []
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
    return events


def _chat_reply(base, prompt):
    reply = post(
        base,
        "/v1/chat/completions",
        {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 192,
            "stream": False,
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    text = reply["choices"][0]["message"]["content"]
    if not text or not text.strip():
        raise RuntimeError(f"Gemma returned no spoken content: {reply}")
    return text


def _speech(base, text):
    audio = post(
        base, "/v1/audio/speech", {"input": text, "voice": "af_heart", "response_format": "wav", "stream": False}
    )
    if audio[:4] != b"RIFF":
        raise RuntimeError("Empty chat reply or invalid speech WAV")
    return audio


def _final_transcript(events):
    finals = [event for event in events if event.get("type") == "transcript.text.done"]
    if len(finals) != 1 or not finals[0].get("text"):
        raise RuntimeError(f"Expected one complete automatic transcript: {events}")
    return finals[0]


@dataclass(frozen=True)
class SavedPcmPass:
    """What one saved-PCM pass produced, so the report reads by name rather than by position."""

    timing: Any
    started: float
    events: list[dict[str, Any]]
    final: dict[str, Any]
    text: str
    audio: bytes


def _saved_pcm_pass(base: str, token: str | None, pcm: bytes, timer: BenchmarkLifecycle) -> SavedPcmPass:
    """One saved-PCM pass: stream, transcribe, answer and speak; returns what the report records."""
    with timer.request() as timing:
        started = time.perf_counter()
        events = _stream_pcm(base, token, pcm)
        final = _final_transcript(events)
        text = _chat_reply(base, final["text"] + " Reply in one short English sentence.")
        audio = _speech(base, text)
    return SavedPcmPass(timing, started, events, final, text, audio)


def _whole_turn_pass(base: str, wav: bytes, timer: BenchmarkLifecycle, language: str) -> tuple[SavedPcmPass, float]:
    """One completed turn through Kobold's own Whisper, which decodes the whole upload after the turn ends."""
    with timer.request() as timing:
        started = time.perf_counter()
        reply = post(base, "/api/extra/transcribe", whole_turn_body(wav, language), binary=True)
        decode_seconds = time.perf_counter() - started
        final: dict[str, Any] = {
            "type": "transcript.text.done",
            "text": reply["text"],
            "observed_at": time.perf_counter(),
        }
        text = _chat_reply(base, final["text"] + " Reply in one short English sentence.")
        audio = _speech(base, text)
    return SavedPcmPass(timing, started, [final], final, text, audio), decode_seconds


class SmokeSession:
    """One runtime's chat server with the practice gateway in front of it, on the smoke's fixed ports."""

    chat_port = 19194
    proxy_port = 19195

    def __init__(self, runtime: str, engine: cfg.AsrStartupEngine, errors: list[str]) -> None:
        self.runtime, self.engine, self.errors = runtime, engine, errors
        self.base = f"http://127.0.0.1:{self.proxy_port}"
        self.process: subprocess.Popen[Any] | None = None
        self.gateway: Any = None
        self.thread: threading.Thread | None = None

    def _on_server(self, value: Any) -> None:
        self.gateway = value

    def cleanup(self) -> None:
        if self.gateway:
            self.gateway.shutdown()
        if self.thread:
            self.thread.join(timeout=10)
        if self.process:
            stop_owned(self.process)

    def setup(self) -> None:
        if launch_util.port_listening(self.proxy_port):
            raise RuntimeError("Smoke gateway port occupied; no session stopped")
        self.process = _start_chat(self.runtime, self.chat_port)
        self.thread = _gateway_thread(
            self.runtime, self.engine, self.proxy_port, self.chat_port, self._on_server, self.errors
        )
        _await_gateway(self.base, self.errors)

    def timer(self) -> BenchmarkLifecycle:
        return BenchmarkLifecycle(
            lambda: str(self.process.pid) if self.process else "reused-matching-server", self.cleanup
        )


def _whole_turn_arm(base: str, wav: bytes, report: dict[str, Any], timer: BenchmarkLifecycle, setup: Any, repeats: int):
    """Kobold's own Whisper has no automatic turns: the page uploads the finished turn, so time that upload."""
    try:
        with timer:
            timer.prepare(setup, combined=True)
            timer.warmup(lambda: http_ready(base + "/health"))
            post(base, "/api/extra/transcribe", whole_turn_body(wav), binary=True)
            passes = [_whole_turn_pass(base, wav, timer, "en") for _ in range(repeats)]
            last, decode_seconds = passes[-1]
            report.update(
                status="completed",
                transcript=last.final["text"],
                reply=last.text,
                wav_bytes=len(last.audio),
                timing=last.timing.record(),
                automatic_turns=False,
                passes=[{"decode_request_seconds": seconds} for _, seconds in passes],
                first_partial_seconds=None,
                decode_request_seconds=decode_seconds,
                final_event=last.final,
                final_after_vad_end_seconds=final_after_speech_end(decode_seconds),
            )
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["benchmark"] = timer.record()


def _live_latency(item: SavedPcmPass) -> dict[str, float | None]:
    """Where one microphone-style pass spent its time, measured from the audio it streamed."""
    return {
        "first_partial_seconds": next(
            (
                event["observed_at"] - item.started
                for event in item.events
                if event.get("type") in ("transcript.text.delta", "transcript.text.snapshot")
                and (event.get("delta") or event.get("text"))
            ),
            None,
        ),
        "final_after_vad_end_seconds": item.final["observed_at"]
        - item.started
        - (item.final["speech_end_sample"] - 512) / 16000,
    }


def _record_live_pass(passes: list[SavedPcmPass], report: dict[str, Any]) -> None:
    """The row the report keeps for microphone-style passes: the last pass plus every pass' latencies."""
    last = passes[-1]
    report.update(
        status="completed",
        transcript=last.final["text"],
        reply=last.text,
        wav_bytes=len(last.audio),
        timing=last.timing.record(),
        passes=[_live_latency(item) for item in passes],
        final_event=last.final,
        **_live_latency(last),
    )


def _live_arm(session: SmokeSession, pcm: bytes, report: dict[str, Any], repeats: int) -> None:
    """A microphone-style pass: stream the saved PCM through the gateway's automatic Silero turns."""
    token = None

    def start_vad():
        nonlocal token
        token = post(session.base, "/asr/live/start", {"language": "en"})["session"]

    def stop_vad() -> None:
        if token:
            post(session.base, f"/asr/live/{token}/stop", b"", True)

    timer = session.timer()
    vad_timer = BenchmarkLifecycle(lambda: token or "", stop_vad)
    try:
        with timer, vad_timer:
            timer.prepare(session.setup, combined=True)
            timer.warmup(lambda: http_ready(session.base + "/health"))
            vad_timer.prepare(start_vad, combined=True)
            vad_timer.warmup(lambda: post(session.base, f"/asr/live/{token}/audio", bytes(1024), True))
            passes = []
            for index in range(repeats):
                passes.append(_saved_pcm_pass(session.base, token, pcm, timer))
                if index + 1 < repeats:
                    # - a fresh session per pass keeps speech_end_sample inside one turn instead of
                    #   accumulating across passes, which made the final-after-speech-end value negative
                    stop_vad()
                    start_vad()
            _record_live_pass(passes, report)
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["benchmark"] = timer.record()
        report["vad_benchmark"] = vad_timer.record()


def exercise(
    runtime: str,
    pcm: bytes,
    wav: bytes,
    report: dict[str, Any],
    engine: cfg.AsrStartupEngine = cfg.AsrStartupEngine.AUDIOCPP,
    repeats: int = 1,
):
    session = SmokeSession(runtime, engine, [])
    if engine is cfg.AsrStartupEngine.EMBEDDED:
        _whole_turn_arm(session.base, wav, report, session.timer(), session.setup, repeats)
    else:
        _live_arm(session, pcm, report, repeats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtimes", nargs="+", choices=("llamacpp", "koboldcpp"), default=("llamacpp", "koboldcpp"))
    parser.add_argument(
        "--engine",
        choices=(
            "audiocpp-nemotron",
            "audiocpp-qwen3",
            "nemo-nemotron",
            "parakeetcpp-nemotron-cpu",
            "speechcpp-qwen-0.6b",
            "whisper-vulkan",
            "parakeetcpp-v3",
            "embedded",
        ),
        default="audiocpp-nemotron",
    )
    parser.add_argument("--resources", action="store_true", help="Sample ASR process CPU/RSS and GPU memory")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1, help="saved-PCM passes per runtime")
    args = parser.parse_args()
    engine = cfg.AsrStartupEngine(args.engine)
    if engine is cfg.AsrStartupEngine.EMBEDDED and "koboldcpp" not in args.runtimes:
        parser.error("Embedded Whisper runs inside KoboldCpp; include koboldcpp in --runtimes")
    context = require_native_execution("Practice gateway smoke")
    refuse_existing_sessions([19193, 19194, 19195, 19196])
    run = CasePaths(__file__).new_run()
    report: dict[str, Any] = {
        "execution_context": context,
        "scope": "Saved PCM through both gateways; no browser microphone/echo/quality evaluation",
        "runtimes": {},
        "engine": args.engine,
    }
    report["provenance"] = provenance.block(
        subject="Practice gateway smoke",
        config={"engine": report["engine"], "runtimes": list(args.runtimes), "scope": report["scope"]},
        frameworks=[
            provenance.framework_state(key) for key in sorted({"audiocpp", ENGINE_COMPONENTS[engine], *args.runtimes})
        ],
        models=[
            provenance.file_identity("chat", cfg.GEMMA_AUDIO_ASR.model),
            provenance.file_identity("asr", engine_model(engine)),
            provenance.file_identity("tts", Path(practice_models.tts_spec()["path"])),
        ],
    )
    samples, rate = decode_audio(Path(default_corpus()[0]["file"]))
    clip_samples = mono_resample(samples, rate, clip=True)
    pcm = (clip_samples * 32767).astype("<i2").tobytes()
    pcm += bytes(64000)
    pcm = pcm.ljust((len(pcm) + 1023) // 1024 * 1024, b"\0")
    wav = pcm_wav(clip_samples, 16000)
    process = None
    started = time.perf_counter()

    def start_speech():
        nonlocal process
        process = selector.backend(engine).start() if engine in cfg.AUDIOCPP_ASR_ENGINES else start_tts()

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
            patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", cfg.KoboldcppSpeechStartupEngine.AUDIOCPP),
            patch.object(cfg.KOBOLDCPP_SERVICE, "model", "llamacpp/gemma-4-E4B-it-Q4_0"),
            patch.dict(cfg.KOBOLDCPP_KCPPS_ARGS, port=19194, port_param=19194),
            patch.object(cfg.KOBOLDCPP_SERVICE, "streaming_ui_port", 19195),
        ):
            speech_timer.prepare(start_speech, combined=True)
            speech_url = (
                asr.url()
                if engine in cfg.AUDIOCPP_ASR_ENGINES
                else f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}"
            )
            speech_timer.warmup(
                lambda: post(
                    speech_url,
                    "/v1/audio/speech",
                    # - The gateway normalizes voice fields per TTS family; the smoke uses the same call
                    practice_models.speech_body(
                        {"model": cfg.LANGUAGE_PRACTICE.tts_model, "input": "Hello.", "response_format": "wav"}
                    ),
                )
            )
            if selector.external(engine) and engine not in cfg.AUDIOCPP_ASR_ENGINES:
                asr_timer.prepare(start_asr, combined=True)
            if engine is not cfg.AsrStartupEngine.EMBEDDED:
                # - Kobold's own Whisper exists only once its server starts, so that arm warms it in place
                from scripts.launchers.shared.transport.multipart import audio_upload

                upload = audio_upload(
                    Path(default_corpus()[0]["file"]).read_bytes(), {"language": "en", "response_format": "json"}
                )
                recognizer_timer = speech_timer if engine in cfg.AUDIOCPP_ASR_ENGINES else asr_timer
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
                    exercise(runtime, pcm, wav, row, engine, args.repeats)
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
