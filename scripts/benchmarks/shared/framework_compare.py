"""Compare the language-practice stack with Lemonade on chat, speech and recognition.

Each backend is started and stopped in turn so one stack holds the GPU at a time. Practice means
this repository's language profile: llama.cpp chat, AudioCpp Kokoro speech and AudioCpp Nemotron
recognition behind the practice gateway. Lemonade answers the same three legs on its own port with
its kokoro and whisper.cpp backends. A leg a stack cannot serve is recorded as unavailable with the
reason the server gave, never dropped.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psutil
import requests

from scripts.benchmarks.shared import language_corpus as corpus
from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector
from scripts.launchers.asr import server as asr_gateway
from scripts.launchers.audiocpp import asr as audiocpp_asr
from scripts.launchers.lemonade_server import lemonade
from scripts.launchers.llamacpp import language_practice
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import get_gpu_memory_snapshot
from scripts.launchers.shared.media.audio import decode_audio
from scripts.launchers.shared.services import native
from scripts.launchers.shared.services.process import http_ready, stop_owned
from scripts.launchers.shared.transport.multipart import audio_upload
from scripts.tests.cases.asr.shared.metrics import pooled_scores, unicode_errors

WARMUP_PROMPT = "Say hello in one short sentence."
PROMPTS = (
    "Describe a quiet scouting mission near an enemy facility with a teammate.",
    "Explain why a small local model can still be useful for practising a language.",
)
# - One sentence per language the practice profile speaks; both stacks are asked for the same voice
TTS_TEXTS = (
    ("en", "en-us", "af_heart", "Good morning. I would like a ticket to the city centre, please."),
    ("es", "es", "ef_dora", "Buenos días. Quisiera un billete para el centro de la ciudad, por favor."),
    ("fr", "fr-fr", "ff_siwis", "Bonjour. Je voudrais un billet pour le centre-ville, s'il vous plaît."),
    ("ja", "ja", "jf_alpha", "おはようございます。市内中心部までの切符をお願いします。"),
)
# - "qwen" is the practice stack with the other installed recogniser, kept as a third arm so the
#   recognition choice stays measured instead of being re-probed by hand
BACKENDS = ("practice", "qwen", "lemonade")
ALTERNATE_ENGINE = cfg.AsrStartupEngine.QWEN3_ASR
LEGS = ("chat", "tts", "asr")
# - Ports are taken from the OS per run: a stack left in TIME_WAIT must not fail the next run
# - Lemonade names these by its own catalog: kokoro-v1 for speech, whisper.cpp models for recognition
LEMONADE_TTS_MODEL = "kokoro-v1"
LEMONADE_ASR_MODEL = "Whisper-Large-v3-Turbo"
DEFAULT_WEIGHTS = model_cfg.path(cfg.LANGUAGE_PRACTICE.llm_model)


@dataclass(frozen=True)
class Served:
    """One running stack and the three endpoints a leg can address."""

    backend: str
    chat: str
    tts: str
    asr: str
    chat_model: str
    tts_model: str
    asr_model: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Options:
    legs: tuple[str, ...]
    tokens: int
    requests_count: int
    clips: int


# ============================================================
# SERVING
# ============================================================


def _free_port() -> int:
    """A port the OS just confirmed is free; exclusive binds refuse a recycled one."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _await_exit(pid: int, timeout_s: float = 90) -> None:
    """Wait until a stopped stack really exited: the next one must not start against held memory."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return
        time.sleep(0.25)
    raise RuntimeError(f"Process {pid} did not exit within {timeout_s:.0f}s; the next stack would share its memory")


def _chat_command(weights: Path, port: int) -> list[str]:
    """The practice chat command, pointed at this run's weights and benchmark port."""
    command = language_practice.chat_command()
    command[command.index("-m") + 1] = str(weights)
    command[command.index("--port") + 1] = str(port)
    return command


def _gateway_thread(
    port: int, engine: cfg.AsrStartupEngine, errors: list[str], box: dict[str, Any]
) -> threading.Thread:
    """Run the practice gateway in-process; it fronts AudioCpp speech and the profile's recogniser."""

    def run_gateway() -> None:
        try:
            asr_gateway.run_proxy(
                engine, "127.0.0.1", port, None, audiocpp_asr.url(), lambda value: box.update(gateway=value)
            )
        except Exception as error:  # a thread cannot raise into the caller
            errors.append(str(error))

    thread = threading.Thread(target=run_gateway, daemon=True)
    thread.start()
    return thread


def _await_gateway(base: str, errors: list[str]) -> None:
    deadline = time.monotonic() + 30
    while not http_ready(base + "/health"):
        if errors:
            raise RuntimeError(errors[0])
        if time.monotonic() > deadline:
            raise TimeoutError(f"Practice gateway did not answer {base}/health")
        time.sleep(0.1)


@contextmanager
def _serve_practice(
    weights: Path, run: RunPaths, recogniser_engine: cfg.AsrStartupEngine | None = None
) -> Iterator[Served]:
    """llama.cpp chat plus the AudioCpp speech/gateway pair of the language profile."""
    errors: list[str] = []
    box: dict[str, Any] = {}
    chat = speech = recogniser = thread = None
    engine = recogniser_engine or cfg.ASR_SERVICE.engine
    chat_port, speech_port, gateway_port = _free_port(), _free_port(), _free_port()
    command = _chat_command(weights, chat_port)
    with (
        patch.object(cfg.LLAMACPP_PRACTICE, "internal_port", chat_port),
        patch.object(cfg, "AUDIOCPP_VAD", replace(cfg.AUDIOCPP_VAD, server_port=speech_port)),
    ):
        try:
            # - The launcher path merges the console instead of wrapping it in PowerShell, which
            #   would strip the quotes out of the JSON-valued server arguments
            chat = native.start_server(
                command,
                (Path(command[0]), weights),
                chat_port,
                "Practice chat benchmark",
                lambda: http_ready(f"http://127.0.0.1:{chat_port}/health"),
                lambda: native.matches(command),
                timeout=240,
                component_key="llamacpp",
            )
            speech = audiocpp_asr.start(speech_port)
            # - The profile's recogniser is its own backend; AudioCpp still provides the speech leg
            if engine is not cfg.AsrStartupEngine.AUDIOCPP:
                recogniser = selector.backend(engine).start()
            base = f"http://127.0.0.1:{gateway_port}"
            thread = _gateway_thread(gateway_port, engine, errors, box)
            _await_gateway(base, errors)
            models = audiocpp_asr.speech_config(speech_port)["models"]
            yield Served(
                backend="practice",
                chat=f"http://127.0.0.1:{chat_port}",
                tts=base,
                asr=base,
                chat_model=weights.stem,
                tts_model=cfg.LANGUAGE_PRACTICE.tts_model,
                asr_model=_recogniser_model(engine, models),
                details={
                    "gateway": base,
                    "ports": {"chat": chat_port, "speech": speech_port, "gateway": gateway_port},
                    "chat_log": str(project_cfg.component("llamacpp").logs_dir),
                    "models": {row["id"]: row["path"] for row in models},
                },
            )
        finally:
            if thread is not None:
                gateway = box.get("gateway")
                if gateway is not None:
                    gateway.shutdown()
                thread.join(timeout=10)
            if recogniser is not None:
                stop_owned(recogniser)
                _await_exit(recogniser.pid)
            if speech is not None:
                stop_owned(speech)
                _await_exit(speech.pid)
            if chat is not None:
                stop_owned(chat)
                _await_exit(chat.pid)


def _recogniser_path(engine: cfg.AsrStartupEngine | None = None) -> Path:
    """The file behind a recogniser, so its identity is recorded with the run."""
    engine = engine or cfg.ASR_SERVICE.engine
    if engine is cfg.AsrStartupEngine.QWEN3_ASR:
        return Path(cfg.QWEN3_ASR.model)
    if engine is cfg.AsrStartupEngine.WHISPER_VULKAN:
        return Path(cfg.WHISPERCPP_ASR.model)
    return Path(str(audiocpp_asr.speech_config(0)["models"][0]["path"]))


def _recogniser_model(engine: cfg.AsrStartupEngine, models: list[dict[str, Any]]) -> str:
    """Readable name for the recogniser that answered, not its internal request id."""
    return _recogniser_path(engine).stem


def _lemonade_catalog(base: str) -> dict[str, Any]:
    """The ids Lemonade reports, so a speech model and the chat model are named, not guessed."""
    try:
        value = requests.get(f"{base}/api/v1/models", params={"show_all": "true"}, timeout=30).json()
    except (requests.RequestException, ValueError):
        return {}
    rows = value if isinstance(value, list) else value.get("data") or []
    return {row["id"]: row for row in rows if isinstance(row, dict) and row.get("id")}


def _lemonade_chat_model(catalog: dict[str, Any], weights: Path) -> str:
    """Lemonade's id for this run's weights; a folder name is not a model."""
    for name, row in catalog.items():
        if name == weights.stem or str(row.get("path", "")).endswith(weights.name):
            return name
    candidates = ", ".join(sorted(catalog)[:8]) or "none"
    raise RuntimeError(f"Lemonade does not list {weights.name}; it offers: {candidates}")


@contextmanager
def _serve_lemonade(weights: Path, run: RunPaths) -> Iterator[Served]:
    """Lemonade's own server on this run's weights; it answers chat, speech and recognition."""
    models_dir = weights.parent
    port = _free_port()
    with lemonade.run_config(models_dir, port):
        process, log = lemonade.start(models_dir, port)
        base = f"http://127.0.0.1:{port}"
        try:
            catalog = _lemonade_catalog(base)
            model = _lemonade_chat_model(catalog, weights)
            # - Ask for the load here: the alternative is Lemonade's own 600 s wait inside the
            #   first chat request, where nothing of ours can see it stall
            loaded = lemonade.load(model, port)
            yield Served(
                backend="lemonade",
                chat=base,
                tts=base,
                asr=base,
                chat_model=model,
                tts_model=LEMONADE_TTS_MODEL,
                asr_model=LEMONADE_ASR_MODEL,
                details={
                    "log": str(log),
                    "port": port,
                    "install": str(cfg.LEMONADE_SERVICE.exe),
                    "backend": {key: loaded.get(key) for key in ("backend_url", "backend_health", "device")},
                    "launch_command": loaded.get("launch_command"),
                    "speech": {
                        name: {"recipe": row.get("recipe"), "downloaded": row.get("downloaded")}
                        for name, row in catalog.items()
                        if name in (LEMONADE_TTS_MODEL, LEMONADE_ASR_MODEL)
                    },
                },
            )
        finally:
            lemonade.stop(process, port)
            _await_exit(process.pid)


def serve(backend: str, weights: Path, run: RunPaths) -> AbstractContextManager[Served]:
    handlers = {
        "practice": _serve_practice,
        "lemonade": _serve_lemonade,
        "qwen": partial(_serve_practice, recogniser_engine=ALTERNATE_ENGINE),
    }
    return handlers[backend](weights, run)


# ============================================================
# CHAT LEG
# ============================================================


def _sse_json(line: bytes) -> dict[str, Any] | None:
    """One server-sent event decoded, or None for keep-alive frames, comments and the terminator."""
    if not line:
        return None
    text = line.decode("utf-8", errors="replace").removeprefix("data:").strip()
    if not text or text == "[DONE]":
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _delta_parts(line: bytes) -> tuple[str | None, str | None]:
    """Content and reasoning a delta carries; a thinking model streams the latter first."""
    value = _sse_json(line)
    if value is None:
        return None, None
    choices = value.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta") or {}
    return delta.get("content") or None, delta.get("reasoning_content") or None


def _delta_text(line: bytes) -> str | None:
    """The content of one server-sent delta, if this event carries any."""
    return _delta_parts(line)[0]


def _error_text(line: bytes) -> str | None:
    """A stream error a server sent instead of content, so an empty reply is explained."""
    value = _sse_json(line)
    error = value.get("error") if value else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)
    return str(error) if error else None


def stream_chat(served: Served, prompt: str, tokens: int) -> dict[str, Any]:
    """One streaming completion; the first content delta is the time to first token."""
    payload = {
        "model": served.chat_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": tokens,
        "temperature": 0,
        "seed": 42,
        "stream": True,
        # - Both stacks must run with thinking off, as the character and language profiles configure it;
        #   without this the wrapped llama.cpp defaults leave a model thinking until the budget ends
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    first: float | None = None
    chunks = 0
    reasoning = 0
    errors: list[str] = []
    with requests.post(f"{served.chat}/v1/chat/completions", json=payload, stream=True, timeout=300) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            error = _error_text(line)
            if error:
                errors.append(error)
                continue
            content, thought = _delta_parts(line)
            if thought:
                reasoning += 1
            if content is None:
                continue
            if first is None:
                first = time.perf_counter() - started
            chunks += 1
    seconds = time.perf_counter() - started
    if chunks == 0 and errors:
        raise RuntimeError(errors[0])
    return {
        "seconds": seconds,
        "first_token_seconds": first,
        "chunks": chunks,
        "reasoning_chunks": reasoning,
        "chunks_per_second": chunks / seconds if seconds > 0 else None,
    }


def _snapshot():
    value = get_gpu_memory_snapshot()
    return asdict(value) if value is not None else None


def _chat_leg(served: Served, options: Options) -> dict[str, Any]:
    before = _snapshot()
    stream_chat(served, WARMUP_PROMPT, options.tokens)
    rows = [stream_chat(served, prompt, options.tokens) for prompt in PROMPTS[: options.requests_count]]
    return {
        "status": "measured",
        "model": served.chat_model,
        "requests": rows,
        "vram_before": before,
        "vram_after": _snapshot(),
    }


# ============================================================
# SPEECH LEG
# ============================================================


def _checked(response: requests.Response, what: str) -> bytes:
    """The body, or an error that carries what the server actually said."""
    if response.status_code >= 400:
        raise RuntimeError(f"{what} returned HTTP {response.status_code}: {response.text[:300]}")
    return response.content


def _speech(served: Served, text: str, voice: str, locale: str) -> tuple[bytes, float]:
    payload: dict[str, Any] = {
        "model": served.tts_model,
        "input": text,
        "voice": voice,
        "response_format": "wav",
        "stream": False,
        "options": {"language": locale},
    }
    started = time.perf_counter()
    response = requests.post(f"{served.tts}/v1/audio/speech", json=payload, timeout=300)
    seconds = time.perf_counter() - started
    data = _checked(response, "Speaker")
    if data[:4] != b"RIFF":
        raise ValueError(f"Speaker returned {len(data)} bytes that are not a WAV")
    return data, seconds


def _tts_row(served: Served, run: RunPaths, text: tuple[str, str, str, str]) -> dict[str, Any]:
    language, locale, voice, sentence = text
    row: dict[str, Any] = {"language": language, "locale": locale, "voice": voice, "characters": len(sentence)}
    try:
        data, seconds = _speech(served, sentence, voice, locale)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        return {**row, "status": "unavailable", "reason": str(error)}
    path = run.artifacts / f"{served.backend}-{language}.wav"
    path.write_bytes(data)
    samples, rate = decode_audio(path)
    audio_seconds = len(samples) / rate if rate else 0.0
    return {
        **row,
        "status": "measured",
        "seconds": seconds,
        "audio_seconds": audio_seconds,
        "real_time_factor": seconds / audio_seconds if audio_seconds else None,
        "file": path.name,
    }


def _tts_leg(served: Served, run: RunPaths) -> dict[str, Any]:
    """Warm the speaker first: its first call carries the backend's own model load."""
    try:
        _speech(served, "One two three.", TTS_TEXTS[0][2], TTS_TEXTS[0][1])
    except (requests.RequestException, RuntimeError, ValueError) as error:
        return {"status": "unavailable", "reason": str(error), "rows": []}
    rows = [_tts_row(served, run, text) for text in TTS_TEXTS]
    measured = [row for row in rows if row["status"] == "measured"]
    return {
        "status": "measured" if measured else "unavailable",
        "reason": "" if measured else next((row.get("reason", "") for row in rows), ""),
        "rows": rows,
    }


# ============================================================
# RECOGNITION LEG
# ============================================================


def _transcribe(served: Served, audio: bytes, language: str) -> tuple[str, float]:
    body, content_type = audio_upload(
        audio, {"model": served.asr_model, "language": language, "response_format": "json"}
    )
    started = time.perf_counter()
    response = requests.post(
        f"{served.asr}/v1/audio/transcriptions", data=body, headers={"Content-Type": content_type}, timeout=300
    )
    seconds = time.perf_counter() - started
    _checked(response, "Recogniser")
    value = response.json()
    text = value.get("text") if isinstance(value, dict) else None
    if not isinstance(text, str):
        raise ValueError("Recogniser returned no transcript")
    return text, seconds


def _asr_row(served: Served, clip: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "clip": clip["id"],
        "language": clip["language"],
        "audio_seconds": clip["duration_seconds"],
        "reference": clip["reference"],
    }
    try:
        text, seconds = _transcribe(served, Path(clip["file"]).read_bytes(), clip["language"])
    except (requests.RequestException, RuntimeError, ValueError) as error:
        return {**row, "status": "unavailable", "reason": str(error)}
    return {
        **row,
        "status": "measured",
        "seconds": seconds,
        "real_time_factor": seconds / clip["duration_seconds"] if clip["duration_seconds"] else None,
        "text": text,
        **unicode_errors(clip["reference"], text),
    }


def _pooled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per language: pooled word and character error rates across that language's clips."""
    languages = list(dict.fromkeys(row["language"] for row in rows))
    return [
        {"language": language, **pooled_scores([row for row in rows if row["language"] == language])}
        for language in languages
    ]


def _asr_leg(served: Served, clips: list[dict[str, Any]]) -> dict[str, Any]:
    # - Japanese is expected to fail on the practice Nemotron backend (see notes/TODO.md); the row
    #   keeps the upstream reason so the gap stays visible instead of turning into a missing line
    rows = [_asr_row(served, clip) for clip in clips]
    measured = [row for row in rows if row["status"] == "measured"]
    return {
        "status": "measured" if measured else "unavailable",
        "reason": "" if measured else next((row.get("reason", "") for row in rows), ""),
        "rows": rows,
        "languages": _pooled(measured),
    }


# ============================================================
# RUN AND REPORT
# ============================================================


def measure(
    backend: str, weights: Path, run: RunPaths, options: Options, clips: list[dict[str, Any]]
) -> dict[str, Any]:
    """Start one stack, exercise each selected leg, then stop it again."""
    started = time.perf_counter()
    # - The whisper arm is the practice stack's second recogniser, so it is not a second stack:
    #   chat and speech are measured once, under the profile default
    legs = ("asr",) if backend == "qwen" else options.legs
    result: dict[str, Any] = {"backend": backend, "legs": {}}
    with serve(backend, weights, run) as served:
        result["startup_seconds"] = time.perf_counter() - started
        result["models"] = {"chat": served.chat_model, "tts": served.tts_model, "asr": served.asr_model}
        result["details"] = served.details
        if "chat" in legs:
            result["legs"]["chat"] = _chat_leg(served, options)
        if "tts" in legs:
            result["legs"]["tts"] = _tts_leg(served, run)
        if "asr" in legs:
            result["legs"]["asr"] = _asr_leg(served, clips)
    return result


def _mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else "n/a"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _chat_summary(results: list[dict[str, Any]]) -> list[str]:
    lines = ["| backend | model | startup s | TTFT s | chunks/s |", "| --- | --- | ---: | ---: | ---: |"]
    for result in results:
        leg = result["legs"].get("chat")
        if not leg:
            continue
        if leg["status"] != "measured":
            lines.append(f"| {result['backend']} | {result['models']['chat']} | n/a | n/a | n/a |")
            continue
        rows = [row for row in leg["requests"] if row["chunks"]]
        if not rows:
            # - A thinking model spends the measured budget before it speaks; that is the answer,
            #   not a missing measurement
            note = "thinking only" if any(row.get("reasoning_chunks") for row in leg["requests"]) else "no content"
            lines.append(
                f"| {result['backend']} | {leg['model']} | {result['startup_seconds']:.1f} | {note} | {note} |"
            )
            continue
        ttft = [row["first_token_seconds"] for row in rows if row["first_token_seconds"] is not None]
        rate = [row["chunks_per_second"] for row in rows if row["chunks_per_second"] is not None]
        lines.append(
            f"| {result['backend']} | {leg['model']} | {result['startup_seconds']:.1f} | "
            f"{_mean(ttft)} | {_mean(rate)} |"
        )
    return lines


def _tts_summary(results: list[dict[str, Any]]) -> list[str]:
    lines = ["| backend | model | language | voice | RTF | audio s |", "| --- | --- | --- | --- | ---: | ---: |"]
    for result in results:
        leg = result["legs"].get("tts")
        if not leg:
            continue
        if leg.get("status") != "measured":
            lines.append(f"| {result['backend']} | {result['models']['tts']} | unavailable | - | - | - |")
            continue
        for row in leg["rows"]:
            if row["status"] != "measured":
                lines.append(f"| {result['backend']} | {result['models']['tts']} | {row['language']} | - | - | - |")
                continue
            lines.append(
                f"| {result['backend']} | {result['models']['tts']} | {row['language']} | {row['voice']} | "
                f"{row['real_time_factor']:.2f} | {row['audio_seconds']:.2f} |"
            )
    return lines


def _asr_summary(results: list[dict[str, Any]]) -> list[str]:
    lines = ["| backend | model | language | clips | WER | CER |", "| --- | --- | --- | ---: | ---: | ---: |"]
    for result in results:
        leg = result["legs"].get("asr")
        if not leg:
            continue
        if leg.get("status") != "measured":
            lines.append(f"| {result['backend']} | {result['models']['asr']} | unavailable | 0 | - | - |")
            continue
        for row in leg["languages"]:
            lines.append(
                f"| {result['backend']} | {result['models']['asr']} | {row['language']} | {row['samples']} | "
                f"{_percent(row['pooled_wer'])} | {_percent(row['pooled_cer'])} |"
            )
    return lines


def _unavailable(results: list[dict[str, Any]]) -> list[str]:
    """Why work could not be measured; a capability gap is evidence, not a silent omission."""
    notes = []
    for result in results:
        for name, leg in result["legs"].items():
            if leg["status"] == "measured":
                failed = [row for row in leg.get("rows") or [] if row["status"] != "measured"]
                reasons = {row.get("reason") or "no measurement" for row in failed}
                if failed:
                    items = ", ".join(str(row.get("clip") or row.get("language")) for row in failed)
                    notes.extend(f"- {result['backend']} {name} {items}: {reason}" for reason in reasons)
                continue
            notes.append(f"- {result['backend']} {name}: {leg.get('reason') or 'no measurement'}")
    return notes


def _script_notes(results: list[dict[str, Any]]) -> list[str]:
    """Word error rate needs word boundaries; scripts without them are read by character."""
    languages = {
        row["language"] for result in results for row in (result["legs"].get("asr") or {}).get("languages") or []
    }
    unspaced = sorted(languages & {"ja", "zh", "yue"})
    return [f"- recognition {'/'.join(unspaced)}: read CER; WER depends on word segmentation"] if unspaced else []


def _duration_notes(results: list[dict[str, Any]]) -> list[str]:
    """Audio that does not match between stacks is a broken comparison, not a speed win."""
    durations: dict[str, dict[str, float]] = {}
    for result in results:
        for row in (result["legs"].get("tts") or {}).get("rows") or []:
            if row["status"] == "measured":
                durations.setdefault(row["language"], {})[result["backend"]] = row["audio_seconds"]
    notes = []
    for language, values in durations.items():
        if len(values) < 2 or not max(values.values()):
            continue
        if min(values.values()) / max(values.values()) < 0.5:
            detail = ", ".join(f"{backend} {value:.2f} s" for backend, value in values.items())
            notes.append(f"- speech {language}: the stacks produced different amounts of audio ({detail})")
    return notes


def summarize(results: list[dict[str, Any]]) -> str:
    """Markdown tables, one per leg, then anything the stacks could not serve or agree on."""
    sections = [
        ("## Chat", _chat_summary(results)),
        ("## Speech", _tts_summary(results)),
        ("## Recognition", _asr_summary(results)),
    ]
    body = "\n\n".join(f"{title}\n\n" + "\n".join(lines) for title, lines in sections)
    notes = [*_unavailable(results), *_duration_notes(results), *_script_notes(results)]
    return body + ("\n\n## Notes\n\n" + "\n".join(notes) if notes else "")


def _source_models(weights: Path) -> list[dict[str, Any]]:
    """Weight files behind both stacks, recorded so a swap is visible later."""
    return [
        provenance.file_identity("chat", weights),
        provenance.file_identity("practice tts", model_cfg.path(cfg.LANGUAGE_PRACTICE.tts_model)),
        provenance.file_identity("practice asr", _recogniser_path()),
        provenance.file_identity("practice asr alternate", _recogniser_path(ALTERNATE_ENGINE)),
        provenance.file_identity("lemonade server", cfg.LEMONADE_SERVICE.exe),
    ]


def _status(results: list[dict[str, Any]], options: Options) -> str:
    measured = sum(
        1 for result in results for leg in options.legs if (result["legs"].get(leg) or {}).get("status") == "measured"
    )
    return "passed" if measured else "failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, help="GGUF the chat leg serves (default: the practice model)")
    parser.add_argument("--backend", choices=(*BACKENDS, "all"), default="all", help="stack to measure")
    parser.add_argument("--legs", nargs="+", choices=LEGS, default=list(LEGS), help="legs to measure")
    parser.add_argument("--tokens", type=int, default=64, help="maximum reply tokens per chat request")
    parser.add_argument("--requests", type=int, default=2, help="measured chat requests per backend")
    parser.add_argument("--clips", type=int, default=80, help="recognition clips from the pinned corpus")
    args = parser.parse_args(argv)
    context = require_native_execution("Language practice comparison")
    paths = BenchmarkPaths(source=__file__).new_run()
    options = Options(
        legs=tuple(dict.fromkeys(args.legs)), tokens=args.tokens, requests_count=args.requests, clips=args.clips
    )
    weights = args.weights or DEFAULT_WEIGHTS
    clips = corpus.prepare(paths)[: options.clips] if "asr" in options.legs else []
    print(f"[INFO] weights: {weights}", flush=True)
    print(f"[INFO] legs: {', '.join(options.legs)}; corpus clips: {len(clips)}", flush=True)
    started = time.perf_counter()
    results = []
    for backend in BACKENDS if args.backend == "all" else (args.backend,):
        print(f"[INFO] measuring {backend}", flush=True)
        results.append(measure(backend, weights, paths, options, clips))
    report = {
        "name": "language practice comparison",
        "category": "model-free wiring; live native run",
        "status": _status(results, options),
        "reasoning": "One stack at a time on the same weights. Chat streams, speech synthesises one sentence per "
        "language, recognition scores the pinned corpus clips by pooled word and character error rate.",
        "provenance": provenance.block(
            subject="language practice versus Lemonade",
            config={
                "legs": list(options.legs),
                "tokens": options.tokens,
                "requests": options.requests_count,
                "clips": options.clips,
                "tts_texts": [{"language": row[0], "locale": row[1], "voice": row[2]} for row in TTS_TEXTS],
                "ports": "one free port set per backend, recorded with each result",
            },
            frameworks=[
                provenance.framework_state("llamacpp"),
                provenance.framework_state("audiocpp"),
                provenance.framework_state("lemonade_server"),
            ],
            models=_source_models(weights),
            corpus=provenance.corpus_state(corpus.identity(), corpus.root()),
        ),
        "tokens": options.tokens,
        "total_seconds": time.perf_counter() - started,
        "results": results,
        "execution_context": context,
    }
    paths.write_report(report)
    table = summarize(results)
    (paths.artifacts / "summary.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    print(f"[OUTPUT] {paths.root}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
