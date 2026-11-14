"""Brief Breeze 2, Ming 3.0, Kokoro or Supertonic TTS checks across AudioCpp release builds."""

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared import provenance as shared_provenance
from scripts.benchmarks.shared.vram import process_evidence, snapshot_dict
from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers.audiocpp.kokoro import audio_environment
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor
from scripts.shared.resources import summarize_resources, watch_resources
from scripts.tests.shared.paths import CasePaths, Outcome, RunPaths

TEXT = "Good morning. How are you today?"


@dataclass(frozen=True)
class TtsProfile:
    key: str
    label: str
    model: Path
    family: str
    seed: int
    options: dict[str, str]
    voice: str = ""


PROFILES = {
    "breeze2": TtsProfile(
        "breeze-q4-test", "Breeze TTS 2 Q4_0", model_cfg.path("audiocpp/breeze-tts-2-q4_0"), "breeze_tts", 123, {}
    ),
    "supertonic": TtsProfile(
        "supertonic-test",
        "Supertonic 3 Q8_0",
        model_cfg.path("audiocpp/supertonic-3-q8_0"),
        "supertonic",
        1234,
        {"voice_id": "F1"},
        voice="F1",
    ),
    "kokoro": TtsProfile(
        "kokoro-test",
        "Kokoro 82M multilingual Q8_0",
        model_cfg.path("audiocpp/kokoro-audiocpp-multilingual-q8_0"),
        "kokoro_tts",
        1234,
        {"language": "en-us"},
        voice="af_heart",
    ),
    "ming3-tts": TtsProfile(
        "ming3-tts-test",
        "Ming 3.0 TTS 0.5B Q8_0",
        model_cfg.path("audiocpp/ming3-tts-0.5b-q8_0"),
        "ming3_tts",
        1895,
        {"language": "en", "template_name": "ip", "voice_id": "US_James"},
    ),
    "ming3-audio": TtsProfile(
        "ming3-audio-test",
        "Ming 3.0 Audio Tiny Q4_K",
        model_cfg.path("audiocpp/ming3-audio-tiny-q4_k"),
        "ming3_audio",
        42,
        {"language": "en", "voice_id": "US_James"},
    ),
}
PORTS = {"vulkan": 18881, "hip": 18882, "hip-7.1-old": 18883, "rocm-release": 18884}
ROCM_RUNTIME_DIRS = {"hip": project_cfg.AUDIOCPP_ROCM_BUILD_DIR, "rocm-release": project_cfg.ROCM_SDK_BIN_DIR}
BUILDS = {
    "vulkan": project_cfg.AUDIOCPP_VULKAN_BIN_DIR / "audiocpp_server.exe",
    "rocm-release": project_cfg.AUDIOCPP_ROCM_BIN_DIR / "audiocpp_server.exe",
    "hip": (
        project_cfg.FRAMEWORKS_DIR
        / "audiocpp"
        / "additions/rocm"
        / "0.9.2-drama3-base-small-therock-10.2-hip-7.17-gfx1101"
        / "build"
        / "bin"
        / "audiocpp_server.exe"
    ),
    "hip-7.1-old": project_cfg.AUDIOCPP_ROCM_LEGACY_DIR / "audiocpp_server.exe",
}
SERVER_BACKENDS = {"vulkan": "vulkan", "hip": "hip", "hip-7.1-old": "hip", "rocm-release": "hip"}
BUILD_COMMITS = {"vulkan": "50749561", "hip": "50749561", "hip-7.1-old": "77186d9"}
BUILD_RELEASES = {
    "vulkan": "v0.9.2-drama3-base-small",
    "hip": "v0.9.2-drama3-base-small",
    "hip-7.1-old": "ROCm 7.1 package (2026-10-03)",
}


def provenance(name: str) -> dict[str, Any]:
    exe = BUILDS[name]
    directory = exe.parent
    marker = directory / ".release_published_at"
    asset = directory / ".release_asset"
    build = directory / "BUILD.json"
    return {
        "exe": str(exe),
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "release_published_at": marker.read_text().strip() if marker.is_file() else None,
        "asset": asset.read_text().strip() if asset.is_file() else None,
        "build": json.loads(build.read_text(encoding="utf-8")) if build.is_file() else None,
    }


def loader_checks(profile: TtsProfile, backends: list[str]) -> int:
    run = CasePaths(__file__).new_run()
    started = time.perf_counter()
    results = []
    for backend in backends:
        cli = BUILDS[backend].with_name("audiocpp_cli.exe")
        completed = subprocess.run(
            [str(cli), "--list-loaders", "--json"], cwd=cli.parent, capture_output=True, timeout=30
        )
        (run.logs / f"loaders-{backend}.stdout.json").write_bytes(completed.stdout)
        (run.logs / f"loaders-{backend}.stderr.log").write_bytes(completed.stderr)
        registered = completed.returncode == 0 and profile.family in completed.stdout.decode("utf-8", errors="replace")
        results.append(
            {
                "backend": backend,
                "registered": registered,
                "exit_code": completed.returncode,
                "provenance": provenance(backend),
            }
        )
        print(f"[{'OK' if registered else 'FAIL'}] {backend}: {profile.family} loader", flush=True)
    passed = all(row["registered"] for row in results)
    run.write_report(
        {
            "name": profile.label + " loader check",
            "category": "audiocpp",
            "status": "completed" if passed else "failed",
            "results": results,
            "execution_context": require_native_execution("AudioCpp loader check"),
            "total_seconds": time.perf_counter() - started,
            "limits": "Family registration only; weights not loaded and no audio synthesized.",
            "provenance": shared_provenance.block(
                subject=profile.label + " loader check",
                config={"backends": backends, "profile": profile.label},
                frameworks=[shared_provenance.framework_state("audiocpp")],
                models=[],
            ),
        }
    )
    print(f"Report: {run.artifacts / 'report.md'}", flush=True)
    return 0 if passed else 1


def health(port: int) -> bool:
    from scripts.launchers.shared.services.process import http_ready

    return http_ready(f"http://127.0.0.1:{port}/health")


def wait_for_health(port: int, process: subprocess.Popen[bytes], timeout_s: float = 90) -> None:
    from scripts.launchers.shared.services.process import wait_ready

    wait_ready(process, lambda: health(port), timeout_s, label=f"AudioCpp on port {port}", interval=0.5)


def make_config(backend: str, path: Path, profile: TtsProfile = PROFILES["breeze2"]) -> None:
    settings = {
        "host": "127.0.0.1",
        "backend": backend,
        "device": 0,
        "lazy_load": True,
        "models": [
            {"id": profile.key, "family": profile.family, "path": str(profile.model), "task": "tts", "mode": "offline"}
        ],
    }
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def generate(port: int, wav_path: Path, profile: TtsProfile, text: str, timeout: float) -> dict[str, Any]:
    options = {**profile.options, "seed": str(profile.seed)}
    payload = {"model": profile.key, "input": text, "response_format": "wav", "options": options}
    if profile.voice:
        payload["voice"] = profile.voice
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    elapsed_s = time.perf_counter() - started
    if not body.startswith(b"RIFF") or body[8:12] != b"WAVE":
        raise RuntimeError(f"expected WAV, received {content_type}; body starts {body[:200]!r}")
    wav_path.write_bytes(body)
    with wave.open(str(wav_path), "rb") as audio:
        audio_s = audio.getnframes() / audio.getframerate()
        rate = audio.getframerate()
        channels = audio.getnchannels()
        if audio_s <= 0 or not any(audio.readframes(audio.getnframes())):
            raise RuntimeError("Generated WAV is empty or entirely silent")
    return {
        "seed": profile.seed,
        "request": payload,
        "elapsed_s": elapsed_s,
        "audio_s": audio_s,
        "rtf": elapsed_s / audio_s if audio_s else None,
        "sample_rate": rate,
        "channels": channels,
        "wav_bytes": len(body),
        "wav": str(wav_path),
    }


def run_backend(
    backend: str,
    run_root: Path,
    profile: TtsProfile = PROFILES["breeze2"],
    count: int = 1,
    text: str = TEXT,
    timeout: float = 45,
) -> dict[str, Any]:
    exe = BUILDS[backend]
    port = PORTS[backend]
    if not exe.is_file():
        raise FileNotFoundError(f"missing executable: {exe}")
    if launch_util.port_listening(port):
        raise RuntimeError(f"port {port} is occupied; refusing to replace it")

    config = run_root / "temp" / f"server-{backend}.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    make_config(SERVER_BACKENDS[backend], config, profile)
    log_path = run_root / "logs" / f"server-{backend}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = audio_environment()
    if backend != "vulkan":
        runtime_dirs = [str(exe.parent)]
        runtime = ROCM_RUNTIME_DIRS.get(backend)
        if runtime is not None:
            runtime_dirs.append(str(runtime))
        env["PATH"] = os.pathsep.join((*runtime_dirs, env.get("PATH", "")))
    baseline = snapshot_dict()
    memory_path = run_root / "logs" / f"vram-{backend}.jsonl"
    traces: list[dict[str, Any]] = []
    stop = threading.Event()
    with log_path.open("wb") as log:
        startup_started = time.perf_counter()
        process = subprocess.Popen(
            [str(exe), "--config", str(config), "--port", str(port), "--threads", "8", "--no-ui"],
            cwd=str(exe.parent),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            env=env,
        )
        launch_util.assign_process_to_job(process.pid)
        monitor = GpuMemoryMonitor(process.pid, memory_path)
        monitor.stage = "startup"
        watcher = threading.Thread(
            target=watch_resources,
            args=(process, stop, traces, time.monotonic() + 240, lambda: monitor.stage),
            daemon=True,
        )
        watcher.start()
        try:
            with monitor:
                wait_for_health(port, process)
                server_startup_s = time.perf_counter() - startup_started
                from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle

                lifecycle = BenchmarkLifecycle(
                    lambda: f"{process.pid}:{profile.model}" if process.poll() is None else ""
                )
                lifecycle.adopt_prepared(server_startup_s, combined=False)
                print(f"{backend}: healthy after {server_startup_s:.2f}s; warming up", flush=True)
                monitor.stage = "warmup"
                warmup_started = time.perf_counter()
                lifecycle.warmup(
                    lambda: generate(port, run_root / "artifacts" / f"{backend}-warmup.wav", profile, text, timeout),
                    includes_model_load=True,
                )
                warmup_s = time.perf_counter() - warmup_started
                monitor.stage = "resident"
                resident = snapshot_dict(process.pid)
                print(f"{backend}: warmup {warmup_s:.2f}s; measuring {count} request(s)", flush=True)
                samples = []
                for index in range(1, count + 1):
                    monitor.stage = f"request-{index}"
                    sample, timing = lifecycle.measure(
                        lambda: generate(
                            port, run_root / "artifacts" / f"{backend}-{index}.wav", profile, text, timeout
                        )
                    )
                    sample.update(timing)
                    samples.append(sample)
        finally:
            stop.set()
            from scripts.launchers.shared.services.process import stop_owned

            stop_owned(process, timeout=20, graceful=True, kill_timeout=10)
            watcher.join(timeout=5)
            (run_root / "logs" / f"resources-{backend}.json").write_text(json.dumps(traces, indent=2), encoding="utf-8")
    memory: dict[str, Any] = process_evidence(monitor, baseline, resident, memory_path)
    for index, sample in enumerate(samples, start=1):
        stage = memory["stage_peaks"].get(f"request-{index}", {})
        sample["vram_peak_process_mib"] = stage.get("process_used_mb")
    return {
        "samples": samples,
        "benchmark": lifecycle.record(),
        "server_startup_s": server_startup_s,
        "warmup_s": warmup_s,
        "instruction_sent": False,
        "vram": memory,
        "resources": summarize_resources(traces),
    }


# - Vulkan is the shipped backend: three screens measured RTF 0.34-0.39 against 0.42-0.47 on the ROCm
#   release, so that arm runs only when asked with --backend rocm-release
DEFAULT_BACKENDS = ("vulkan",)
LIMITATIONS = (
    "Offline generation only; one short prompt with the recorded sample count per backend. "
    "The backends produced different audio durations despite the same seed, so this is a short throughput screen, "
    "not a quality comparison or a definitive backend ranking. Request elapsed time excludes server startup and "
    "the warmup request; warmup_s includes model loading and first inference, so it is not a pure model-load timer. "
    "No instruct option is supplied; profiles record fixed voice options when supported. Breeze uses each build's default voice. "
    "VRAM peaks are sampled lower bounds. Windows per-process dedicated allocations can exceed adapter physical usage; "
    "counter polling can affect CPU load."
)


def _arguments() -> tuple[argparse.Namespace, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="run every configured build")
    selection.add_argument("--backend", choices=tuple(BUILDS), help="run only this build")
    parser.add_argument("--case", choices=tuple(PROFILES), default="breeze2")
    parser.add_argument("--samples", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--text", default=TEXT)
    parser.add_argument("--timeout", type=int, choices=range(10, 121), default=45)
    parser.add_argument("--loaders-only", action="store_true", help="check family registration without loading weights")
    args = parser.parse_args()
    try:
        context = require_native_execution("AudioCpp")
    except RuntimeError as error:
        parser.error(str(error))
    return args, context


def _selected_backends(args: argparse.Namespace) -> list[str]:
    if args.all:
        return list(BUILDS)
    if args.backend:
        return [args.backend]
    return list(DEFAULT_BACKENDS)


def _apply_provenance(selected: list[str]) -> dict[str, Any]:
    metadata = {name: provenance(name) for name in selected}
    for name, info in metadata.items():
        BUILD_RELEASES[name] = info["asset"] or BUILD_RELEASES.get(name, "unknown")
        BUILD_COMMITS[name] = (info["build"] or {}).get("source_sha", "unknown; see asset provenance")
    return metadata


def _document(
    args: argparse.Namespace,
    profile: TtsProfile,
    context: dict[str, Any],
    selected: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": profile.label + " Vulkan versus ROCm release check",
        "category": "probes",
        "build_releases": BUILD_RELEASES,
        "build_commits": BUILD_COMMITS,
        "model": str(profile.model),
        "model_bytes": profile.model.stat().st_size,
        "text": args.text,
        "case": args.case,
        "options": profile.options,
        "instruction": "not supplied; explicit voice/language options are recorded per profile",
        "mode": "offline",
        "warmups_per_backend": 1,
        "measured_runs_per_backend": args.samples,
        "builds": {name: str(path) for name, path in BUILDS.items()},
        "selected_backends": selected,
        "execution_context": context,
        "provenance": metadata,
        "model_sha256": hashlib.sha256(profile.model.read_bytes()).hexdigest(),
        "status": "running",
        "results": {},
        "errors": {},
    }


def _backend_summary(backend_result: dict[str, Any]) -> dict[str, Any]:
    samples = backend_result["samples"]
    return {
        "samples": samples,
        "server_startup_s": backend_result["server_startup_s"],
        "warmup_s": backend_result["warmup_s"],
        "instruction_sent": backend_result["instruction_sent"],
        "vram": backend_result["vram"],
        "resources": backend_result["resources"],
        "median_elapsed_s": statistics.median(item["elapsed_s"] for item in samples),
        "median_audio_s": statistics.median(item["audio_s"] for item in samples),
        "median_rtf": statistics.median(item["rtf"] for item in samples),
    }


def _collect_backend(
    result: dict[str, Any],
    backend: str,
    selected: list[str],
    run: RunPaths,
    profile: TtsProfile,
    args: argparse.Namespace,
) -> bool:
    """Run one build; returns True when the remaining builds should be skipped."""
    try:
        result["results"][backend] = _backend_summary(
            run_backend(backend, run.root, profile, args.samples, args.text, args.timeout)
        )
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        result["errors"][backend] = message
        print(f"{backend}: {message}", flush=True)
        if not (isinstance(error, TimeoutError) and "did not answer /health" in str(error)):
            return False
        result["skipped_backends"] = selected[selected.index(backend) + 1 :]
        if result["skipped_backends"]:
            print("Stopping remaining builds after a server startup health timeout.", flush=True)
        return True
    return False


def _collect_backends(
    result: dict[str, Any], selected: list[str], run: RunPaths, profile: TtsProfile, args: argparse.Namespace
) -> None:
    for backend in selected:
        if _collect_backend(result, backend, selected, run, profile, args):
            break


def _write_samples_csv(run: RunPaths, result: dict[str, Any]) -> None:
    sample_columns: tuple[str, ...] = (
        "backend",
        "release",
        "commit",
        "sample",
        "seed",
        "server_startup_s",
        "warmup_s",
        "elapsed_s",
        "audio_s",
        "rtf",
        "sample_rate",
        "vram_peak_process_mib",
        "channels",
        "wav_bytes",
        "wav",
        "request",
    )
    # - Samples carry lifecycle fields (status, request_seconds, marks, error)
    #   from BenchmarkLifecycle; keep them instead of failing the CSV write.
    sample_columns = (
        *sample_columns,
        *sorted(
            {key for summary in result["results"].values() for sample in summary["samples"] for key in sample}
            - set(sample_columns)
        ),
    )
    with (run.artifacts / "samples.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=sample_columns)
        writer.writeheader()
        for backend, summary in result["results"].items():
            for index, sample in enumerate(summary["samples"], start=1):
                writer.writerow(
                    {
                        "backend": backend,
                        "release": BUILD_RELEASES[backend],
                        "commit": BUILD_COMMITS[backend],
                        "server_startup_s": summary["server_startup_s"],
                        "warmup_s": summary["warmup_s"],
                        "sample": index,
                        **sample,
                    }
                )


def _write_summary_csv(run: RunPaths, result: dict[str, Any]) -> None:
    summary_columns = (
        "backend",
        "release",
        "commit",
        "server_startup_s",
        "warmup_s",
        "measured_runs",
        "median_elapsed_s",
        "median_audio_s",
        "median_rtf",
        "vram_resident_process_mib",
        "vram_peak_process_mib",
        "vram_peak_adapter_mib",
    )
    with (run.artifacts / "summary.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=summary_columns)
        writer.writeheader()
        for backend, summary in result["results"].items():
            writer.writerow(
                {
                    "backend": backend,
                    "release": BUILD_RELEASES[backend],
                    "commit": BUILD_COMMITS[backend],
                    "server_startup_s": summary["server_startup_s"],
                    "warmup_s": summary["warmup_s"],
                    "measured_runs": len(summary["samples"]),
                    "median_elapsed_s": summary["median_elapsed_s"],
                    "median_audio_s": summary["median_audio_s"],
                    "median_rtf": summary["median_rtf"],
                    "vram_resident_process_mib": (summary["vram"]["resident"] or {}).get("process_used_mb"),
                    "vram_peak_process_mib": summary["vram"]["peak_process_used_mb"],
                    "vram_peak_adapter_mib": summary["vram"]["peak_total_used_mb"],
                }
            )


def _write_tables(run: RunPaths, result: dict[str, Any]) -> Path:
    report = run.artifacts / "summary.json"
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    _write_samples_csv(run, result)
    _write_summary_csv(run, result)
    return report


def _comparison_lines(result: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## Measured comparison",
        "",
        "| Backend | Server startup (s) | Warmup/model load + first request (s) | Median request (s) | Median audio (s) | Median RTF |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for backend, summary in result["results"].items():
        lines.append(
            f"| {backend} | {summary['server_startup_s']:.2f} | {summary['warmup_s']:.2f} | "
            f"{summary['median_elapsed_s']:.2f} | "
            f"{summary['median_audio_s']:.2f} | {summary['median_rtf']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Sampled VRAM (MiB)",
            "",
            "| Backend | Resident process | Peak process | Peak adapter total |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for backend, summary in result["results"].items():
        memory = summary["vram"]
        resident = (memory["resident"] or {}).get("process_used_mb")
        values = [
            "unavailable" if value is None else f"{value:.1f}"
            for value in (resident, memory["peak_process_used_mb"], memory["peak_total_used_mb"])
        ]
        lines.append(f"| {backend} | {' | '.join(values)} |")
    lines.extend(["", result["limitations"], ""])
    return lines


def _write_report(run: RunPaths, result: dict[str, Any], complete: bool, report: Path) -> None:
    run.write_report(
        {
            "name": result["name"],
            "category": "probes",
            "status": "completed" if complete else "incomplete",
            "outcome": result["outcome"],
            "total_seconds": result["total_seconds"],
            "reasoning": result["reasoning"],
            "limitations": result["limitations"],
            "provenance": shared_provenance.block(
                subject=result["name"],
                config={
                    "case": result["case"],
                    "options": result["options"],
                    "text": result["text"],
                    "selected_backends": result["selected_backends"],
                    "warmups_per_backend": result["warmups_per_backend"],
                    "measured_runs_per_backend": result["measured_runs_per_backend"],
                },
                frameworks=[shared_provenance.framework_state("audiocpp")],
                models=[shared_provenance.file_identity("tts", Path(result["model"]))],
            ),
        }
    )
    with (run.artifacts / "report.md").open("a", encoding="utf-8") as output:
        output.write("\n".join(_comparison_lines(result)))
    print(f"Report: {report}", flush=True)


def _print_comparison(result: dict[str, Any]) -> None:
    for backend, summary in result["results"].items():
        print(
            f"{backend}: median {summary['median_elapsed_s']:.2f}s, "
            f"audio {summary['median_audio_s']:.2f}s, RTF {summary['median_rtf']:.2f}",
            flush=True,
        )


def main() -> int:
    args, context = _arguments()
    print(f"[OK] Execution context: {json.dumps(context)}", flush=True)
    selected = _selected_backends(args)
    profile = PROFILES[args.case]
    if args.loaders_only:
        return loader_checks(profile, selected)
    metadata = _apply_provenance(selected)
    started = time.perf_counter()
    run = CasePaths(__file__).new_run(Outcome.INCONCLUSIVE)
    run.artifacts.mkdir(parents=True, exist_ok=True)
    result = _document(args, profile, context, selected, metadata)
    print(f"Run: {run.root}", flush=True)
    _collect_backends(result, selected, run, profile, args)
    complete = len(result["results"]) == len(selected)
    result["status"] = "complete" if complete else "partial"
    result["outcome"] = "inconclusive"
    result["total_seconds"] = round(time.perf_counter() - started, 3)
    result["reasoning"] = "not applicable"
    result["limitations"] = LIMITATIONS
    report = _write_tables(run, result)
    _write_report(run, result, complete, report)
    _print_comparison(result)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
