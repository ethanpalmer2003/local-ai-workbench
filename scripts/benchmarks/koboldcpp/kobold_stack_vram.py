"""Measure the configured Kobold/audio stack, then add the sd.cpp proxy."""

import argparse
import base64
import io
import json
import struct
import subprocess
import sys
import time
import wave
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

from scripts.benchmarks.shared import preflight as preflight_check
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.config.audiocpp import server as audio_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp_catalog
from scripts.launchers.koboldcpp import external_llm, kobold
from scripts.launchers.runtime import shared_gpu
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor, get_gpu_memory_snapshot
from scripts.tests.cases.koboldcpp.kobold_audiocpp_modes import speech_request
from scripts.tests.shared import backends
from scripts.tests.shared import benchmark_config as benchmark_cfg
from scripts.tests.shared.http_server import request
from scripts.tests.shared.resources import summarize_resources, watch_resources

llm_mode = "kobold"
SPEECH_TEXT = "Hello there, this is a short voice test."


def text_target() -> tuple[int, str]:
    """Kobold's own model, or the llama.cpp server that replaces it."""
    if llm_mode == "external":
        return cfg.LLAMACPP_SERVICE.internal_port, external_llm.ALIAS
    return backends.ports("kobold")[0], cfg.KOBOLDCPP_SERVICE.model


def _request_spec(kind: str, text: str, text_port: int | None) -> tuple[dict[str, object], int, str]:
    if kind == "text":
        target_port, target_model = text_target()
        payload: dict[str, object] = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": "Write a descriptive spoken reply of five complete sentences; no list or heading.",
                },
                {
                    "role": "user",
                    "content": "Describe a quiet scouting mission near an enemy facility with a teammate.",
                },
            ],
            "max_tokens": 128,
            "temperature": 0.1,
            "seed": 42,
            "stream": False,
        }
        return payload, text_port if text_port is not None else target_port, "/v1/chat/completions"
    if kind == "audio":
        return (
            {
                "model": cfg.AUDIOCPP_SERVICE.model,
                "voice": cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value,
                "input": text[:240],
                "stream": True,
                "response_format": "pcm",
                "stream_format": "sse",
                "options": {"seed": "4321"},
            },
            backends.ports("audio")[0],
            "/v1/audio/speech",
        )
    return (
        {"prompt": "a red cube on a white background", "seed": 42, "response_format": "b64_json"},
        backends.ports("image")[0],
        "/v1/images/generations",
    )


def _perform_request(
    kind: str, port: int, route: str, payload: dict[str, object], text: str
) -> tuple[dict[str, Any] | None, int, bytes, str]:
    """Speech goes through the streaming client; everything else is one JSON POST."""
    if kind != "audio":
        status, body, content_type = request(f"http://127.0.0.1:{port}{route}", payload, timeout=90)
        return None, status, body, content_type
    speech = speech_request(text[:240], 90)
    pcm = speech.pop("pcm")
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(pcm)
        return speech, 200, buffer.getvalue(), "audio/wav"


def _describe_text(result: dict[str, Any], body: bytes) -> str:
    result["response"] = json.loads(body)
    text = result["response"]["choices"][0]["message"]["content"].strip()
    if len(text) < 64:
        raise RuntimeError("Kobold returned fewer than 64 characters; not a useful combined-generation workload")
    return text


def _describe_audio(result: dict[str, Any], paths: RunPaths, label: str, body: bytes) -> None:
    (paths.artifacts / f"{label}.wav").write_bytes(body)
    with wave.open(io.BytesIO(body), "rb") as audio:
        frames = audio.getnframes()
        pcm = audio.readframes(frames)
        result["audio_seconds"] = frames / audio.getframerate()
        if not frames or not any(pcm):
            raise RuntimeError("Audio response is empty or silent")


def _describe_image(result: dict[str, Any], paths: RunPaths, label: str, body: bytes) -> None:
    image = base64.b64decode(json.loads(body)["data"][0]["b64_json"], validate=True)
    (paths.artifacts / f"{label}.png").write_bytes(image)
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Image response is not PNG")
    result["dimensions"] = struct.unpack(">II", image[16:24])
    expected = cfg.SDCPP_REQUEST_DEFAULTS["width"], cfg.SDCPP_REQUEST_DEFAULTS["height"]
    if result["dimensions"] != expected:
        raise RuntimeError(f"Expected image {expected}, received {result['dimensions']}")


def _describe_result(
    kind: str,
    paths: RunPaths,
    label: str,
    body: bytes,
    content_type: str,
    speech: dict[str, Any] | None,
    started: float,
) -> tuple[dict[str, Any], str | None]:
    result: dict[str, Any] = {"kind": kind, "seconds": time.monotonic() - started, "content_type": content_type}
    if speech is not None:
        result["streaming"] = speech
    if kind == "text":
        return result, _describe_text(result, body)
    if kind == "audio":
        _describe_audio(result, paths, label, body)
        return result, None
    _describe_image(result, paths, label, body)
    return result, None


def generate(
    kind: str, paths: RunPaths, label: str, text: str = SPEECH_TEXT, text_port: int | None = None
) -> str | None:
    """Run one generation; return the reply text, or None for audio and image kinds."""
    started = time.monotonic()
    payload, port, route = _request_spec(kind, text, text_port)
    (paths.artifacts / f"{label}-{kind}-request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        speech, status, body, content_type = _perform_request(kind, port, route, payload, text)
    except TimeoutError:
        (paths.artifacts / f"{label}-{kind}-result.json").write_text(
            json.dumps({"kind": kind, "status": "timeout", "seconds": time.monotonic() - started}, indent=2),
            encoding="utf-8",
        )
        raise TimeoutError(f"{label} {kind} exceeded the 90-second request limit") from None
    if status != 200:
        (paths.logs / f"{label}-{kind}-error.txt").write_bytes(body)
        raise RuntimeError(f"{kind} HTTP {status}: {body[:300]!r}")
    result, prompt_text = _describe_result(kind, paths, label, body, content_type, speech, started)
    (paths.artifacts / f"{label}-{kind}-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[OK] {label} {kind}: {result['seconds']:.2f}s", flush=True)
    return prompt_text


def _measure_sequence(
    paths: RunPaths,
    monitor: GpuMemoryMonitor,
    report: dict[str, Any],
    start_backend: Callable[[str], None],
    resource_samples: dict[str, list[dict[str, Any]]],
) -> None:
    with monitor:
        monitor.stage = "baseline"
        time.sleep(6)
        monitor.stage = "kobold_loading"
        start_backend("kobold")
        monitor.stage = "kobold_loaded"
        time.sleep(6)
        monitor.stage = "audio_loading"
        start_backend("audio")
        monitor.stage = "audio_cold_generation"
        generate("audio", paths, "audio-cold")
        for combo in ("kobold_audio", "kobold_audio_image"):
            if combo.endswith("image"):
                monitor.stage = "image_loading"
                start_backend("image")
                monitor.stage = "image_warmup"
                generate("image", paths, "image-warmup")
            monitor.stage = combo + "_idle"
            time.sleep(8)
            monitor.stage = combo + "_text"
            reply = generate("text", paths, combo + "-serial")
            monitor.stage = combo + "_audio"
            generate("audio", paths, combo + "-serial", reply or SPEECH_TEXT)
            if combo.endswith("image"):
                monitor.stage = combo + "_image"
                generate("image", paths, combo + "-serial")
            monitor.stage = combo + "_after"
            time.sleep(6)
            (paths.artifacts / "vram.json").write_text(json.dumps(monitor.summary(), indent=2), encoding="utf-8")
        if report.get("guard_abort") or any(row.get("abort") for rows in resource_samples.values() for row in rows):
            raise RuntimeError("Benchmark resource guard triggered; inspect resource traces")
        report["status"] = "passed"


def _finish(
    paths: RunPaths,
    report: dict[str, Any],
    monitor: GpuMemoryMonitor,
    stop: Event,
    watchers: list[Thread],
    resource_samples: dict[str, list[dict[str, Any]]],
    owned: list[subprocess.Popen[Any]],
    started: float,
) -> None:
    stop.set()
    for watcher in watchers:
        watcher.join(timeout=3)
    (paths.logs / "resources.json").write_text(json.dumps(resource_samples, indent=2), encoding="utf-8")
    report["resources"] = {name: summarize_resources(samples) for name, samples in resource_samples.items()}
    for process in reversed(owned):
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
            process.wait(timeout=10)
    deadline = time.monotonic() + 5
    while owned and any(
        backends.listening(port) for backend in ("kobold", "audio", "image") for port in backends.ports(backend)
    ):
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    report["total_seconds"] = time.monotonic() - started
    report["vram"] = monitor.summary()
    report["remaining_ports"] = {
        backend: [p for p in backends.ports(backend) if backends.listening(p)]
        for backend in ("kobold", "audio", "image")
    }
    report["limits"] = (
        "Sampled dedicated allocation can miss transient peaks; process counters can overlap. Short prompts do not fill Kobold context."
    )
    (paths.artifacts / "vram.json").write_text(json.dumps(monitor.summary(), indent=2), encoding="utf-8")
    paths.write_report(report)
    print(
        json.dumps({key: report.get(key) for key in ("status", "error", "guards", "total_seconds", "remaining_ports")}),
        flush=True,
    )


def preflight() -> None:
    """Fail in seconds: paths, mode flags and free ports before any model load."""
    external = llm_mode == "external"
    inputs = (
        {"llama.cpp server": external_llm.server_exe(), "llama.cpp model": external_llm.model_path()}
        if external
        else {"kobold model": cfg.KOBOLDCPP_MODELS[cfg.KOBOLDCPP_SERVICE.model]}
    )
    inputs["audio config"] = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    preflight_check.require_paths(inputs)
    if external and not external_llm.no_model_config().is_file():
        raise FileNotFoundError("Derived no-model config was not written")
    preflight_check.require_free_ports(
        {
            "kobold": backends.ports("kobold")[-1],
            "audio": backends.ports("audio")[0],
            "image": backends.ports("image")[0],
        }
    )
    audio_config = audio_cfg.read(inputs["audio config"])
    if not any(model["id"] == cfg.AUDIOCPP_SERVICE.model for model in audio_config["models"]):
        raise ValueError(f"AudioCpp model {cfg.AUDIOCPP_SERVICE.model} is not in the server config")
    preflight_check.announce(f"{llm_mode} mode")


def _watch_backend(
    backend: str,
    paths: RunPaths,
    owned: list[subprocess.Popen[Any]],
    stop: Event,
    monitor: GpuMemoryMonitor,
    started: float,
    resource_samples: dict[str, list[dict[str, Any]]],
    watchers: list[Thread],
) -> None:
    import psutil

    backends.start(backend, paths, owned, usage_profile="shared", llm=llm_mode)
    port = (
        cfg.LLAMACPP_SERVICE.internal_port
        if backend == "kobold" and llm_mode == "external"
        else backends.ports(backend)[-1]
    )
    deadline = time.monotonic() + 180
    while not launch_util.listening_process_ids(port) and time.monotonic() < deadline:
        # - the external server loads after Kobold's UI port is already answering
        time.sleep(1)
    pid = launch_util.listening_process_ids(port)[0]
    target = SimpleNamespace(pid=pid, poll=lambda: None if psutil.pid_exists(pid) else 0)
    samples: list[dict[str, Any]] = []
    resource_samples[backend] = samples
    thread = Thread(
        target=watch_resources, args=(target, stop, samples, started + 600, lambda: monitor.stage, started), daemon=True
    )
    watchers.append(thread)
    thread.start()


def _ram_guard(
    stop: Event, started: float, minimum_free_ram_gib: float, owned: list[subprocess.Popen[Any]], report: dict[str, Any]
) -> None:
    import psutil

    while not stop.wait(0.5):
        if time.monotonic() > started + 600 or psutil.virtual_memory().available < minimum_free_ram_gib * 2**30:
            report["guard_abort"] = f"600-second deadline or available RAM below {minimum_free_ram_gib} GiB"
            for process in reversed(owned):
                if process.poll() is None:
                    launch_util.kill_process_tree(process.pid)
            return


def _require_environment() -> dict[str, Any]:
    """Refuse the run in seconds when sessions, ports or config cannot support it."""
    if launch_util.llama_server_running():
        raise RuntimeError("Local llama-server is active; confirm session safety before this GPU workload")
    for backend in ("kobold", "audio", "image"):
        backends.require_free(backend)
    audio_config = audio_cfg.read(Path(cfg.AUDIOCPP_SERVER_ARGS["config"]))
    audio_model = next(model for model in audio_config["models"] if model["id"] == cfg.AUDIOCPP_SERVICE.model)
    if Path(audio_model["path"]).name != "breeze-tts-2-q4_0.gguf":
        raise ValueError("This probe requires the configured Breeze 2 Q4_0 model")
    if audiocpp_catalog.resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value) is None:
        raise FileNotFoundError("Configured voice reference is missing")
    return audio_model


def _settings(audio_model: dict[str, Any], guards: dict[str, Any]) -> dict[str, Any]:
    return {
        "kobold": asdict(cfg.KOBOLDCPP_SERVICE),
        "kobold_args": cfg.KOBOLDCPP_KCPPS_ARGS,
        "llm_mode": llm_mode,
        "kobold_effective_command": kobold.server_command("shared", no_model=llm_mode == "external"),
        "kobold_shared_model_args": kobold.model_overrides("shared"),
        "kobold_model": str(cfg.KOBOLDCPP_MODELS[cfg.KOBOLDCPP_SERVICE.model]),
        "audio_model": audio_model,
        "audio_service": asdict(cfg.AUDIOCPP_SERVICE),
        "image_args": cfg.SDCPP_SERVER_ARGS,
        "usage_profile": "shared",
        "guards": guards,
        "image_shared_args": shared_gpu.IMAGE_ARGS,
        "audio_shared_session_options": shared_gpu.AUDIO_SESSION_OPTIONS,
        "audio_offload_applied": shared_gpu.AUDIO_SESSION_OPTIONS.get(audio_model["family"], {}),
        "image_defaults": cfg.SDCPP_REQUEST_DEFAULTS,
        "automatic_warmup": False,
        "gpu_sampling_interval_seconds": 0.1,
        "resource_sampling_interval_seconds": 0.5,
    }


def run() -> None:
    context = dict(require_native_execution("Combined Kobold/AudioCpp/sd.cpp benchmark"))
    paths = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {paths.root}", flush=True)
    started = time.monotonic()
    owned: list[subprocess.Popen[Any]] = []
    monitor = GpuMemoryMonitor(None, paths.logs / "vram.jsonl", fast_windows=True)
    stop = Event()
    resource_samples: dict[str, list[dict[str, Any]]] = {}
    watchers: list[Thread] = []
    minimum_free_ram_gib = benchmark_cfg.MINIMUM_FREE_RAM_GIB
    report: dict[str, Any] = {
        "name": "Kobold + Breeze Q4_0 + optional sd.cpp VRAM",
        "category": "probes",
        "status": "running",
        "reasoning": "Configured Kobold model and native settings",
        "execution_context": context,
        "guards": {"minimum_free_ram_gib": minimum_free_ram_gib, "whole_run_seconds": 600},
    }

    def start_backend(backend: str) -> None:
        _watch_backend(backend, paths, owned, stop, monitor, started, resource_samples, watchers)

    try:
        audio_model = _require_environment()
        settings = _settings(audio_model, report["guards"])
        (paths.artifacts / "settings.json").write_text(json.dumps(settings, indent=2, default=str), encoding="utf-8")
        if get_gpu_memory_snapshot() is None:
            raise RuntimeError("GPU counters unavailable; run from a normal host terminal")
        Thread(target=_ram_guard, args=(stop, started, minimum_free_ram_gib, owned, report), daemon=True).start()
        preflight()
        _measure_sequence(paths, monitor, report, start_backend, resource_samples)
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        _finish(paths, report, monitor, stop, watchers, resource_samples, owned, started)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("kobold", "audio", "image"))
    parser.add_argument("--llm", choices=("kobold", "external"), default="kobold")
    args = parser.parse_args()
    global llm_mode
    llm_mode = args.llm
    if args.worker:
        sys.argv = [sys.argv[0]]
        backends.worker(args.worker)
    else:
        run()


if __name__ == "__main__":
    main()
