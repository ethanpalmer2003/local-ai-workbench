"""Inspect Drama 3 placement and compare isolated Vulkan/official ROCm CPU-expert offload."""

import argparse
import functools
import hashlib
import http.server
import json
import re
import struct
import subprocess
import threading
import time
import traceback
import urllib.request
import wave
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.vram import snapshot_dict
from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_cfg
from scripts.config.models.gguf_metadata import _read_str, _skip_value
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp_catalog
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor
from scripts.tests.cases.audiocpp.audiocpp_backend_compare import (
    BUILDS,
    SERVER_BACKENDS,
    health,
    provenance,
    wait_for_health,
)
from scripts.tests.cases.audiocpp.audiocpp_transport import AudioReader
from scripts.tests.shared.backends import listening

MODEL = project_cfg.AUDIOCPP_MODELS_DIR / "drama-3-backbone-8bit-experts-Q2_K.gguf"
MODEL_ID = cfg.AudiocppModel.FISH_DRAMA3_Q2.value
PORT = 18884


def weight_estimates() -> dict[str, Any]:  # noqa: C901
    # - Tensor offsets include alignment padding; do not read tensor payloads.
    with MODEL.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError("Expected GGUF")
        version, count, metadata_count = struct.unpack("<IQQ", stream.read(20))
        if version not in (2, 3):
            raise ValueError(f"Unsupported GGUF version {version}")
        alignment = 32
        original_names = []
        for _ in range(metadata_count):
            key = _read_str(stream)
            kind = struct.unpack("<I", stream.read(4))[0]
            if key == "general.alignment" and kind == 4:
                alignment = struct.unpack("<I", stream.read(4))[0]
            elif key == "audiocpp.tensor_names" and kind == 9:
                element_kind, length = struct.unpack("<IQ", stream.read(12))
                if element_kind != 8:
                    raise ValueError("Expected string tensor names")
                original_names = [_read_str(stream) for _ in range(length)]
            else:
                _skip_value(stream, kind)
        tensors: list[tuple[int, str]] = []
        for _ in range(count):
            name = _read_str(stream)
            if name.startswith("_audiocpp."):
                name = original_names[int(name.split(".")[1])]
            dimensions = struct.unpack("<I", stream.read(4))[0]
            stream.seek(dimensions * 8 + 4, 1)
            offset = struct.unpack("<Q", stream.read(8))[0]
            tensors.append((offset, name))
        data_start = (stream.tell() + alignment - 1) // alignment * alignment
    tensors.sort()
    total = MODEL.stat().st_size - data_start
    experts = [0] * 40
    for index, (offset, name) in enumerate(tensors):
        end = tensors[index + 1][0] if index + 1 < len(tensors) else total
        match = re.search(r"layers\.(\d+)\.mlp\.experts\.", name)
        if match:
            experts[int(match[1])] += end - offset
    if not all(experts):
        raise ValueError("Expected routed expert banks in each of 40 layers")
    return {
        "model": str(MODEL),
        "file_bytes": MODEL.stat().st_size,
        "tensor_bytes_with_padding": total,
        "expert_bytes_by_layer": experts,
        "note": "Weight storage only; excludes KV cache, graphs, scratch, driver and other applications. Runtime storage can differ.",
        "placements": [
            {
                "cpu_expert_layers": layers,
                "cpu_weight_gib": sum(experts[:layers]) / 2**30,
                "gpu_weight_gib": (total - sum(experts[:layers])) / 2**30,
                "whole_weight_cpu_fraction": sum(experts[:layers]) / total,
            }
            for layers in (0, 8, 16, 24, 32, 36, 40)
        ],
    }


def server_config(layers: int, path: Path, backend: str = "vulkan") -> None:
    path.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "backend": backend,
                "device": 0,
                "lazy_load": True,
                "models": [
                    {
                        "id": MODEL_ID,
                        "family": "fish_drama3",
                        "path": str(MODEL),
                        "task": "tts",
                        "mode": "streaming",
                        "session_options": {
                            "fish_drama3.cpu_expert_layers": layers,
                            "fish_drama3.context_length": 2048,
                        },
                        "default_request_options": {"max_tokens": 500},
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def measure(
    timeout: float, path: Path, text: str = "A quick test of Drama Three.", max_tokens: int = 160
) -> dict[str, Any]:
    reference = audiocpp_catalog.resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
    if reference is None:
        raise FileNotFoundError("Drama 3 requires an installed voice reference")
    payload = {
        "model": MODEL_ID,
        "input": text,
        "voice_ref": reference[0],
        "reference_text": reference[1],
        "stream": True,
        "stream_format": "sse",
        "response_format": "pcm",
        "options": {"seed": "123", "max_tokens": str(max_tokens), "text_chunk_size": "2000"},
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/audio/speech",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    reader = AudioReader("sse", 44100)
    started = time.perf_counter()
    first_audio = None
    arrivals = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.headers.get_content_type() != "text/event-stream":
            raise RuntimeError(f"Expected SSE, received {response.headers}")
        while chunk := response.read1(8192):
            added = reader.feed(chunk)
            if added:
                arrival = time.perf_counter() - started
                arrivals.append({"arrival_s": arrival, "audio_s": added / (reader.rate * 2)})
                if first_audio is None:
                    first_audio = arrival
            if time.perf_counter() - started > timeout:
                raise TimeoutError("Drama 3 request exceeded total request budget")
    reader.finish()
    elapsed = time.perf_counter() - started
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, reader.rate, 0, "NONE", "not compressed"))
        wav.writeframes(reader.pcm)
    duration = len(reader.pcm) / (reader.rate * 2)
    return {
        "request": payload,
        "first_audio_s": first_audio,
        "elapsed_s": elapsed,
        "audio_s": duration,
        "rtf": elapsed / duration,
        "audio_seconds_per_second": duration / elapsed,
        "arrivals": arrivals,
        "wav": str(path),
    }


def run_case(
    layers: int,
    run: RunPaths,
    timeout: float,
    text: str,
    max_tokens: int,
    label: str | None = None,
    monitor: GpuMemoryMonitor | None = None,
    build: str = "vulkan",
) -> dict[str, Any]:
    if listening(PORT):
        raise RuntimeError(f"Test port {PORT} occupied; refusing to replace service")
    label = label or f"cpu-{layers}"
    config = run.temp / f"server-{label}.json"
    server_config(layers, config, SERVER_BACKENDS[build])
    cfg.AUDIOCPP_SERVICE.model = MODEL_ID
    cfg.AUDIOCPP_SERVICE.port = PORT
    cfg.AUDIOCPP_SERVICE.voice = ""
    cfg.AUDIOCPP_SERVICE.streaming.pcm_sample_rate = 44100
    exe = BUILDS[build]
    result: dict[str, Any] = {
        "build": build,
        "provenance": provenance(build),
        "cpu_expert_layers": layers,
        "execution_context": require_native_execution("Drama 3"),
    }
    result["baseline"] = snapshot_dict()
    started = time.perf_counter()
    with (run.logs / f"server-{label}.log").open("wb") as log:
        process = subprocess.Popen(
            [str(exe), "--config", str(config), "--port", str(PORT), "--threads", "8", "--no-ui"],
            cwd=str(exe.parent),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        launch_util.assign_process_to_job(process.pid)
        result["process_id"] = process.pid
        monitor = monitor or GpuMemoryMonitor(process.pid, run.logs / f"vram-{label}.jsonl")
        monitor.pid = process.pid
        watchdog = threading.Timer(240, process.terminate)
        watchdog.start()
        try:
            with monitor:
                monitor.stage = "startup"
                wait_for_health(PORT, process)
                result["startup_s"] = time.perf_counter() - started
                for stage in ("warmup", "request"):
                    monitor.stage = stage
                    print(f"[OK] CPU expert layers {layers}: {stage}", flush=True)
                    result[stage] = (
                        measure(timeout, run.artifacts / f"{label}-{stage}.wav")
                        if stage == "warmup"
                        else measure(timeout, run.artifacts / f"{label}-{stage}.wav", text, max_tokens)
                    )
                    result[f"{stage}_memory"] = snapshot_dict(process.pid)
        except Exception:
            result["error"] = traceback.format_exc()
            print(result["error"], flush=True)
        finally:
            watchdog.cancel()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
            result["memory"] = monitor.summary()
    return result


def serve(layers: int, run: RunPaths) -> None:  # noqa: C901
    # - Lazy loading keeps unselected catalog models unloaded.
    from scripts.launchers.audiocpp.audiocpp_proxy import _transform
    from scripts.launchers.audiocpp.tts_proxy import run_tts_json_proxy
    from scripts.launchers.proxy_restart import (
        OwnedBackendLifecycle,
        ProxyRestartController,
        reload_proxy_configuration,
    )

    if any(listening(port) for port in (8888, 18886, PORT)):
        raise RuntimeError("Audio proxy/test port occupied; reuse or stop the existing session explicitly")
    config = run.temp / "server-interactive.json"
    source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    settings = audio_cfg.read(source)
    for model in settings["models"]:
        if model["id"] == cfg.AudiocppModel.BREEZE_TTS.value:
            model["mode"] = "streaming"
        if model["id"] == MODEL_ID:
            model["session_options"]["fish_drama3.cpu_expert_layers"] = layers
    config.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    cfg.AUDIOCPP_SERVER_ARGS["config"] = str(config)
    cfg.AUDIOCPP_SERVICE.model = cfg.AudiocppModel.BREEZE_TTS.value
    cfg.AUDIOCPP_SERVICE.port = 8888
    cfg.AUDIOCPP_SERVICE.streaming.pcm_sample_rate = 24000
    exe = project_cfg.AUDIOCPP_SERVER_EXE
    with (run.logs / "server-interactive.log").open("wb") as log:
        process = subprocess.Popen(
            [str(exe), "--config", str(config), "--port", str(PORT), "--threads", "8", "--no-ui"],
            cwd=str(exe.parent),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        lifecycle: OwnedBackendLifecycle | None = None
        try:
            wait_for_health(PORT, process)

            def prepare_backend() -> None:
                updated = audio_cfg.read(source)
                for model in updated["models"]:
                    if model["id"] == cfg.AudiocppModel.BREEZE_TTS.value:
                        model["mode"] = "streaming"
                config.write_text(json.dumps(updated, indent=2), encoding="utf-8")

            interactive_monitor = GpuMemoryMonitor(process.pid, run.logs / "vram-interactive.jsonl")

            def start_backend():
                started = subprocess.Popen(
                    [str(exe), "--config", str(config), "--port", str(PORT), "--threads", "8", "--no-ui"],
                    cwd=str(exe.parent),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                interactive_monitor.pid = started.pid
                interactive_monitor.stage = f"interactive-pid-{started.pid}"
                return started

            service = cfg.AUDIOCPP_SERVICE
            lifecycle = OwnedBackendLifecycle(
                process, start_backend, f"http://127.0.0.1:{PORT}/health", prepare_backend
            )

            def reload_settings() -> None:
                reload_proxy_configuration(service, "AUDIOCPP_SERVICE")
                cfg.AUDIOCPP_SERVER_ARGS["config"] = str(config)

            controller = ProxyRestartController(
                {"backend": lifecycle.restart, "proxy": reload_settings},
                {"backend": [source, Path(cfg.__file__)], "proxy": [Path(cfg.__file__)]},
            )
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(project_cfg.SCRIPTS_DIR))
            page_server = http.server.ThreadingHTTPServer(("127.0.0.1", 18886), handler)
            threading.Thread(target=page_server.serve_forever, daemon=True).start()
            with interactive_monitor:
                print(f"[OK] Audio HTML proxy on http://127.0.0.1:8888; Drama CPU expert layers={layers}", flush=True)
                print("[OK] Test page: http://127.0.0.1:18886/tests/ui/speech.html", flush=True)
                try:
                    run_tts_json_proxy(service, f"http://127.0.0.1:{PORT}", _transform, restart_controller=controller)
                finally:
                    page_server.shutdown()
                    page_server.server_close()
        finally:
            if lifecycle is not None:
                process = lifecycle.process
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layers", nargs="+", type=int, choices=range(1, 41), default=[40])
    parser.add_argument("--build", nargs="+", choices=("vulkan", "rocm-release"), default=["vulkan"])
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--request-timeout", type=float, default=100)
    parser.add_argument("--text", default="A quick test of Drama Three.")
    parser.add_argument("--max-tokens", type=int, default=160)
    args = parser.parse_args()
    run = BenchmarkPaths(__file__).new_run()
    estimates = weight_estimates()
    (run.artifacts / "weight-estimates.json").write_text(json.dumps(estimates, indent=2), encoding="utf-8")
    print(json.dumps(estimates["placements"], indent=2), flush=True)
    print(f"Evidence: {run.root}", flush=True)
    if args.inspect:
        return 0
    context = require_native_execution("Drama 3 offload experiment")
    print(json.dumps(context), flush=True)
    print(json.dumps({f"health_{port}": health(port) for port in (8888, 8889, PORT)}), flush=True)
    if args.serve:
        if args.build != ["vulkan"]:
            parser.error("Interactive serve uses the default Vulkan launcher; --build selects measured runs only")
        serve(args.layers[0], run)
        return 0
    started = time.perf_counter()
    with MODEL.open("rb") as source:
        model_hash = hashlib.file_digest(source, "sha256").hexdigest()
    results = []
    for build in args.build:
        for layers in args.layers:
            result = run_case(
                layers,
                run,
                args.request_timeout,
                args.text,
                args.max_tokens,
                label=f"{build}-cpu-{layers}",
                build=build,
            )
            results.append(result)
            (run.artifacts / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            if result.get("error"):
                break
    run.write_report(
        {
            "name": "Drama 3 backend / CPU expert offload",
            "category": "probes",
            "status": "failed" if any(r.get("error") for r in results) else "completed",
            "reasoning": "Fixed-text streaming screen with separate short warmup; inspect saved WAVs for quality.",
            "execution_context": context,
            "total_seconds": time.perf_counter() - started,
            "model_sha256": model_hash,
        }
    )
    return 1 if any(r.get("error") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
