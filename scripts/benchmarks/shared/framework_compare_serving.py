"""Starting, probing and stopping a backend for the framework comparison."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psutil
import requests

from scripts.benchmarks.shared.paths import RunPaths
from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers import lemonade_server as lemonade
from scripts.launchers.asr import selector
from scripts.launchers.asr import server as asr_gateway
from scripts.launchers.audiocpp import asr as audiocpp_asr
from scripts.launchers.koboldcpp import kobold
from scripts.launchers.launch_util import wait_for_backend
from scripts.launchers.llamacpp import language_practice
from scripts.launchers.shared.services import native
from scripts.launchers.shared.services.process import stop_owned
from scripts.shared.wait import http_ready, wait_ready

# - "whisper" is the practice stack with its other installed recogniser, kept as a third arm
ALTERNATE_ENGINE = cfg.AsrStartupEngine.WHISPER_VULKAN
KOBOLD_ARM_MODEL = cfg.LANGUAGE_PRACTICE.llm_model
KOBOLD_STARTUP_TIMEOUT_S = 240
# - Lemonade names these by its own catalog: kokoro-v1 for speech, whisper.cpp models for recognition
LEMONADE_TTS_MODEL = "kokoro-v1"
LEMONADE_ASR_MODEL = "Whisper-Large-v3-Turbo"


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
    # - "kobold" posts base64 audio to /api/extra/transcribe; the other arms use multipart
    asr_style: str = "openai"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Options:
    legs: tuple[str, ...]
    tokens: int
    requests_count: int
    clips: int


# --- SERVING ---


def _free_port() -> int:
    """A port the OS just confirmed is free; exclusive binds refuse a recycled one."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _await_exit(pid: int, timeout_s: float = 90) -> None:
    """Wait until a stopped stack really exited: the next one must not start against held memory."""

    def gone() -> bool:
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return True
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE

    wait_ready(gone, timeout_s, label=f"process {pid} exit", interval=0.25)


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
    wait_ready(
        lambda: http_ready(base + "/health"),
        30,
        label="practice gateway",
        interval=0.1,
        fail=lambda: errors[0] if errors else None,
    )


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
        process, log = lemonade.start(models_dir, port, owned=True)
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


@contextmanager
def _serve_koboldcpp(weights: Path, run: RunPaths) -> Iterator[Served]:
    """KoboldCpp alone: its own chat, its built-in Kokoro and its embedded whisper, one process."""
    port = _free_port()
    settings = replace(
        cfg.KOBOLDCPP_SERVICE,
        model=KOBOLD_ARM_MODEL,
        speech_engine=cfg.KoboldcppSpeechStartupEngine.KOKORO_INTERNAL,
        transcription_engine=cfg.AsrStartupEngine.EMBEDDED,
    )
    # - A free port per run: the configured 5002 may hold a session the user started
    arguments = {**cfg.KOBOLDCPP_KCPPS_ARGS, "port": port, "port_param": port}
    with patch.object(cfg, "KOBOLDCPP_SERVICE", settings), patch.dict(cfg.KOBOLDCPP_KCPPS_ARGS, arguments):
        process, _, log = kobold.start_kobold("standalone", owned=True)
        base = f"http://127.0.0.1:{port}"
        try:
            if not wait_for_backend(port, KOBOLD_STARTUP_TIMEOUT_S):
                raise TimeoutError(f"KoboldCpp did not answer on port {port} within {KOBOLD_STARTUP_TIMEOUT_S}s")
            yield Served(
                backend="kobold",
                chat=base,
                tts=base,
                asr=base,
                chat_model=model_cfg.path(settings.model).stem,
                tts_model=cfg.KOKORO_TTS.koboldcpp_model.stem,
                asr_model=Path(str(arguments["whispermodel"])).stem,
                # - Kobold posts base64 audio to /api/extra/transcribe instead of multipart uploads
                asr_style="kobold",
                details={
                    "log": str(log),
                    "port": port,
                    "exe": str(cfg.KOBOLDCPP_SERVICE.exe),
                    "weights": str(model_cfg.path(settings.model)),
                    "speech_engine": settings.speech_engine.value,
                    "transcription_engine": getattr(settings.transcription_engine, "value", "off"),
                    "tts_model": str(cfg.KOKORO_TTS.koboldcpp_model),
                    "whisper_model": str(arguments["whispermodel"]),
                    "comparison_weights": str(weights),
                },
            )
        finally:
            stop_owned(process)
            _await_exit(process.pid)


def serve(backend: str, weights: Path, run: RunPaths) -> AbstractContextManager[Served]:
    handlers = {
        "practice": _serve_practice,
        "lemonade": _serve_lemonade,
        "whisper": partial(_serve_practice, recogniser_engine=ALTERNATE_ENGINE),
        "kobold": _serve_koboldcpp,
    }
    return handlers[backend](weights, run)
