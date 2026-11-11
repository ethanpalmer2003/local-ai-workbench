"""Bounded CPU Kokoro or Vulkan image comparisons of embedded and external engines."""

import argparse
import base64
import hashlib
import io
import json
import os
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from scripts.benchmarks.shared import reporting
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp import kokoro
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.sdcpp import server as sdcpp
from scripts.tests.shared.backends import listening
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.resources import summarize_resources, watch_resources

PORT = 18881
TEXTS = (
    "Hello. Tell me about your day, and I will help you practice a natural conversation.",
    "Imagine that we are meeting at a small cafe. Please order a drink, ask about the menu, "
    "and tell me where you would like to sit. After you finish, I will suggest one useful correction.",
)
PROMPT = (
    "A small wooden cabin beside a calm mountain lake, pine trees, morning sunlight, detailed landscape, no people."
)
IMAGE = {"width": 512, "height": 512, "steps": 12, "cfg_scale": 4.0, "clip_skip": 2, "seed": 42}


def post(path: str, body: dict[str, Any], timeout: float, port: int = PORT) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            first = response.read(4096)
            first_seconds = time.perf_counter() - started
            data = first + response.read()
            content_type = response.headers.get("Content-Type")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read(2000).decode(errors='replace')}") from error
    return data, {
        "seconds": time.perf_counter() - started,
        "first_body_seconds": first_seconds,
        "content_type": content_type,
        "response_bytes": len(data),
    }


def sample(kind: str, arm: str, index: int, paths: RunPaths, deadline: float) -> dict[str, Any]:
    timeout = min(90, deadline - time.monotonic())
    if timeout <= 0:
        raise TimeoutError("Whole-run budget exhausted")
    if kind == "tts":
        import soundfile as sf

        body: dict[str, Any] = {
            "model": cfg.LANGUAGE_PRACTICE.tts_model,
            "input": TEXTS[max(index, 0) % len(TEXTS)],
            "voice": cfg.KOKORO_TTS.voice,
            "response_format": "wav",
            "stream": False,
            "speed": 1,
            "seed": 42,
        }
        if arm == "external":
            body["options"] = {"language": cfg.KOKORO_TTS.language}
        data, result = post("/v1/audio/speech", body, timeout)
        info = sf.info(io.BytesIO(data))
        if info.duration <= 0:
            raise ValueError("Empty synthesized audio")
        result.update(
            duration_seconds=info.duration, sample_rate=info.samplerate, rtf=result["seconds"] / info.duration
        )
        suffix = ".wav"
    else:
        native = {
            "negative_prompt": str(cfg.SDCPP_REQUEST_DEFAULTS["negative_prompt"]),
            "clip_skip": IMAGE["clip_skip"],
            "seed": IMAGE["seed"],
            "sample_params": {
                "eta": 1.0,
                "sample_method": "euler_a",
                "sample_steps": IMAGE["steps"],
                "guidance": {"txt_cfg": IMAGE["cfg_scale"]},
            },
        }
        body = {
            "prompt": PROMPT + " ",
            "negative_prompt": native["negative_prompt"],
            "sampler_name": "Euler a",
            "eta": 1.0,
            **IMAGE,
        }
        path = "/sdapi/v1/txt2img"
        if arm == "external":
            path = "/v1/images/generations"
            body = {
                "prompt": PROMPT + " <sd_cpp_extra_args>" + json.dumps(native) + "</sd_cpp_extra_args>",
                "size": "512x512",
                "n": 1,
                "response_format": "b64_json",
            }
        payload, result = post(path, body, timeout)
        value = json.loads(payload)
        data = base64.b64decode(value["images"][0] if arm == "internal" else value["data"][0]["b64_json"])
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.size != (512, 512):
                raise ValueError(f"Unexpected dimensions: {image.size}")
            result["image_metadata"] = {
                key: value for key, value in image.info.items() if isinstance(value, (str, int, float))
            }
        suffix = ".png"
    destination = paths.artifacts / ("warmup" if index < 0 else f"sample-{index}")
    destination = destination.with_suffix(suffix)
    destination.write_bytes(data)
    result.update(file=str(destination), request=body, sha256=hashlib.sha256(data).hexdigest())
    return result


def chat_command(port: int) -> list[str]:
    return [
        str(cfg.KOBOLDCPP_SERVICE.exe),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--model",
        str(cfg.KOBOLDCPP_MODELS["llamacpp/gemma-4-E4B-it-Q4_0"]),
        "--usevulkan",
        "0",
        "--gpulayers",
        "999",
        "--contextsize",
        "16384",
        "--threads",
        str(cfg.KOKORO_TTS.threads),
        "--whispermodel",
        str(cfg.KOBOLDCPP_KCPPS_ARGS["whispermodel"]),
    ]


def command(kind: str, arm: str, paths: RunPaths, with_chat: bool = False) -> list[str]:
    if kind == "tts" and arm == "external":
        return kokoro.audio_command(PORT, paths.temp / "kokoro.json")
    if arm == "internal":
        result = [str(cfg.KOBOLDCPP_SERVICE.exe), "--nomodel", "--host", "127.0.0.1", "--port", str(PORT)]
        if kind == "tts":
            if with_chat:
                return chat_command(PORT) + [
                    "--ttsmodel",
                    str(cfg.KOKORO_TTS.koboldcpp_model),
                    "--ttsthreads",
                    str(cfg.KOKORO_TTS.threads),
                ]
            return result + [
                "--usecpu",
                "--ttsmodel",
                str(cfg.KOKORO_TTS.koboldcpp_model),
                "--ttsthreads",
                str(cfg.KOKORO_TTS.threads),
            ]
        return result + [
            "--usevulkan",
            "0",
            "--sdmodel",
            cfg.SDCPP_MODELS["nova3d-q4"],
            "--sdthreads",
            str(cfg.KOKORO_TTS.threads),
            "--sdconvdirect",
            "full",
            "--sdclipdevice",
            "main",
        ]
    return [
        str(sdcpp.build_dir("vulkan") / "sd-server.exe"),
        "-m",
        cfg.SDCPP_MODELS["nova3d-q4"],
        "--listen-ip",
        "127.0.0.1",
        "--listen-port",
        str(PORT),
        "--rng",
        "cpu",
        "--threads",
        str(cfg.KOKORO_TTS.threads),
        "--diffusion-fa",
    ]


def wait_ready(process: subprocess.Popen[Any], deadline: float, port: int = PORT) -> None:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Backend exited with {process.returncode}; inspect server.log")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise TimeoutError("Backend readiness budget exhausted")


@contextmanager
def extra_chat(paths: RunPaths, enabled: bool, deadline: float, env: dict[str, str]):
    if not enabled:
        yield None
        return
    with (paths.logs / "chat.log").open("wb") as log:
        process = subprocess.Popen(
            chat_command(PORT + 1), cwd=project_cfg.BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        launch_util.assign_process_to_job(process.pid)
        try:
            wait_ready(process, min(deadline, time.monotonic() + 60), PORT + 1)
            yield process
        finally:
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
            process.wait(timeout=15)


def conversation(arm: str, paths: RunPaths, deadline: float) -> dict[str, Any]:
    import soundfile as sf

    chat_port = PORT if arm == "internal" else PORT + 1
    audio = base64.b64encode((paths.artifacts / "sample-0.wav").read_bytes()).decode()
    data, asr = post(
        "/api/extra/transcribe",
        {"audio_data": audio, "langcode": "en"},
        min(60, deadline - time.monotonic()),
        chat_port,
    )
    transcript = json.loads(data)["text"].strip()
    if not transcript:
        raise ValueError("Whisper returned an empty transcript")
    body = {
        "messages": [
            {"role": "system", "content": "You are an English language partner. Reply in one short sentence."},
            {"role": "user", "content": transcript},
        ],
        "max_tokens": 48,
        "temperature": 0,
        "seed": 42,
    }
    data, chat = post("/v1/chat/completions", body, min(60, deadline - time.monotonic()), chat_port)
    reply = json.loads(data)["choices"][0]["message"]["content"].strip()
    if not reply:
        raise ValueError("Gemma returned an empty reply")
    payload: dict[str, Any] = {
        "model": cfg.LANGUAGE_PRACTICE.tts_model,
        "input": reply,
        "voice": cfg.KOKORO_TTS.voice,
        "stream": False,
        "response_format": "wav",
    }
    if arm == "external":
        payload["options"] = {"language": cfg.KOKORO_TTS.language}
    data, speech = post("/v1/audio/speech", payload, min(90, deadline - time.monotonic()))
    if sf.info(io.BytesIO(data)).duration <= 0:
        raise ValueError("Empty spoken reply")
    (paths.artifacts / "conversation.wav").write_bytes(data)
    return {
        "transcript": transcript,
        "reply": reply,
        "asr_seconds": asr["seconds"],
        "chat_seconds": chat["seconds"],
        "tts_seconds": speech["seconds"],
        "roundtrip_seconds": asr["seconds"] + chat["seconds"] + speech["seconds"],
    }


def run_arm(
    kind: str, arm: str, paths: RunPaths, context: dict[str, Any], count: int, deadline: float, with_chat: bool = False
) -> dict[str, Any]:
    cmd = command(kind, arm, paths, with_chat)
    result: dict[str, Any] = {"arm": arm, "command": cmd, "samples": [], "status": "running"}
    model = (
        Path(cfg.SDCPP_MODELS["nova3d-q4"])
        if kind == "image"
        else (cfg.KOKORO_TTS.koboldcpp_model if arm == "internal" else cfg.KOKORO_TTS.audiocpp_model)
    )
    with model.open("rb") as source:
        result["model"] = {
            "path": str(model),
            "bytes": model.stat().st_size,
            "sha256": hashlib.file_digest(source, "sha256").hexdigest(),
        }
    result["version"] = subprocess.check_output(
        [cmd[0], "--version"], text=True, encoding="utf-8", errors="replace"
    ).strip()
    env = kokoro.audio_environment() if kind == "tts" and arm == "external" else os.environ.copy()
    env.update(TEMP=str(cfg.LAUNCH.temp_dir), TMP=str(cfg.LAUNCH.temp_dir), OMP_NUM_THREADS=str(cfg.KOKORO_TTS.threads))
    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    env["PATH"] = str(Path(cmd[0]).parent) + os.pathsep + env.get("PATH", "")
    samples, stop = [], threading.Event()
    started = time.perf_counter()
    with (
        (paths.logs / "server.log").open("wb") as log,
        BenchmarkVram(paths, context) as memory,
        extra_chat(paths, with_chat and arm == "external", deadline, env) as chat,
    ):
        process = subprocess.Popen(cmd, cwd=project_cfg.BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
        launch_util.assign_process_to_job(process.pid)
        watcher = None
        try:
            wait_ready(process, min(deadline, time.monotonic() + 60))
            result["startup_seconds"] = time.perf_counter() - started
            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{kind}:{arm}" if process.poll() is None else "")
            lifecycle.adopt_prepared(result["startup_seconds"])
            import psutil

            children = psutil.Process(process.pid).children(recursive=True)
            workers = [child for child in children if child.name().lower() == Path(cmd[0]).name.lower()]
            resource_pid = workers[-1].pid if workers else process.pid
            result["resource_pid"] = resource_pid
            memory.watch_backend(arm, [resource_pid])
            if chat:
                memory.watch_backend("chat", [chat.pid])
            watched = SimpleNamespace(pid=resource_pid, poll=process.poll)
            watcher = threading.Thread(
                target=watch_resources,
                args=(watched, stop, samples, deadline, lambda: memory.stage, started),
                daemon=True,
            )
            watcher.start()
            memory.stage = "warmup"
            lifecycle.warmup(
                lambda: result.update(warmup=sample(kind, arm, -1, paths, deadline)), includes_model_load=True
            )
            memory.stage = "measured"
            for index in range(count):
                row, timing = lifecycle.measure(lambda: sample(kind, arm, index, paths, deadline))
                row.update(timing)
                result["samples"].append(row)
                print(f"[{arm}] {index + 1}/{count}: {row['seconds']:.3f}s", flush=True)
            result["median_seconds"] = statistics.median(row["seconds"] for row in result["samples"])
            if with_chat:
                memory.stage = "conversation"
                result["conversation"] = conversation(arm, paths, deadline)
            result["status"] = "completed"
            result["benchmark"] = lifecycle.record()
        except Exception as error:
            result.update(status="failed", error=str(error))
        finally:
            memory.stage = "cleanup"
            stop.set()
            if watcher:
                watcher.join(timeout=5)
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
            process.wait(timeout=15)
            result["resources"] = summarize_resources(samples)
            result["total_seconds"] = time.perf_counter() - started
            (paths.logs / "resources.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
    (paths.artifacts / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def write_summary(run: RunPaths, kind: str) -> None:
    rows = []
    for arm in ("internal", "external"):
        path = run.root / arm / "artifacts" / "results.json"
        if not path.is_file():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["status"] != "completed":
            continue
        values = result["samples"]
        ram = result["resources"]["phases"]["measured"]["process_rss_bytes"]["maximum"] / 2**30
        if kind == "tts":
            short = statistics.median(value["seconds"] for value in values[::2])
            long = statistics.median(value["seconds"] for value in values[1::2]) if len(values) > 1 else None
            rtf = statistics.median(value["rtf"] for value in values)
            rows.append(f"| {arm} | {short:.3f} | {f'{long:.3f}' if long else '-'} | {rtf:.3f} | {ram:.2f} |")
        else:
            memory = json.loads((path.parent / "vram.json").read_text(encoding="utf-8"))
            peak = memory["adapter"]["stage_peaks"].get("measured", {}).get("total_used_mb")
            peak_text = f"{peak / 1024:.2f}" if peak is not None else "unavailable"
            rows.append(f"| {arm} | {result['median_seconds']:.3f} | {peak_text} | {ram:.2f} |")
    header = (
        "| Engine | Short text seconds | Long text seconds | Median RTF | Sampled process peak GiB |\n|---|---:|---:|---:|---:|"
        if kind == "tts"
        else "| Engine | Median image seconds | Sampled adapter peak GiB | Sampled process peak GiB |\n|---|---:|---:|---:|"
    )
    text = f"# Embedded versus external {kind}\n\n{header}\n" + "\n".join(rows)
    text += (
        "\n\n- Whole-adapter GPU usage includes desktop/other allocations; peaks are sampled lower bounds.\n"
        "- Server workers are sampled after readiness, including Kobold's extracted child executable.\n"
        "- Check report.json settings.with_chat: isolated runs omit LLM/STT; profile smoke runs also load Gemma and Whisper.\n"
        "- TTS: CPU, five threads, af_heart, matching English texts and buffered WAV requests. "
        "Different Q4/Q8 packages and phonemizers; identical underlying weights are not established. "
        "RTF is generation seconds divided by generated audio seconds. No listening-quality ranking.\n"
        "- Images: identical quantized checkpoint, Vulkan, 512x512, 12 Euler A steps, CFG 4, CLIP skip 2, seed 42, ETA 1. "
        "One prompt/resolution does not establish general image performance or quality.\n"
        "- Commands, versions, model hashes, requests and resource traces are saved beside each arm.\n"
        "- Compare internal/artifacts/sample-0 and external/artifacts/sample-0 for matching media.\n"
    )
    (run.artifacts / "comparison.md").write_text(text, encoding="utf-8")
    if kind == "image" and all(
        (run.root / arm / "artifacts/sample-0.png").is_file() for arm in ("internal", "external")
    ):
        from PIL import Image, ImageDraw

        canvas = Image.new("RGB", (1024, 542), "#20242c")
        draw = ImageDraw.Draw(canvas)
        for index, arm in enumerate(("internal", "external")):
            draw.text(
                (index * 512 + 12, 9),
                "Kobold embedded sd.cpp" if arm == "internal" else "External sd.cpp",
                fill="white",
            )
            with Image.open(run.root / arm / "artifacts/sample-0.png") as image:
                canvas.paste(image.convert("RGB"), (index * 512, 30))
        canvas.save(run.artifacts / "comparison.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("tts", "image"), required=True)
    parser.add_argument("--arms", nargs="+", choices=("internal", "external"), default=["internal", "external"])
    parser.add_argument("--samples", type=int, choices=range(1, 5), default=2)
    parser.add_argument(
        "--with-chat", action="store_true", help="Also load Gemma and Whisper and check a spoken conversation"
    )
    args = parser.parse_args()
    if args.with_chat and args.kind != "tts":
        parser.error("--with-chat is a TTS profile smoke check")
    context = dict(require_native_execution("Embedded/external engine comparison"))
    import psutil

    native_names = {"koboldcpp-nocuda.exe", "koboldcpp.exe", "audiocpp_server.exe", "sd-server.exe", "llama-server.exe"}
    active = [p.info["name"] for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() in native_names]
    if active:
        raise RuntimeError(f"Existing native sessions detected: {active}; no service was stopped")
    if listening(PORT) or (args.with_chat and listening(PORT + 1)):
        raise RuntimeError(f"Port {PORT} is occupied; existing service was not changed")
    run = CasePaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    deadline = time.monotonic() + 240
    with report_run(
        run,
        "koboldcpp/kobold_embedded_compare",
        "audio" if args.kind == "tts" else "image",
        settings={
            "kind": args.kind,
            "with_chat": args.with_chat,
            "execution_context": context,
            "threads": cfg.KOKORO_TTS.threads,
            "voice": cfg.KOKORO_TTS.voice,
            "samples": args.samples,
            "image": IMAGE,
            "limits": "Check with_chat for LLM/STT residency; TTS uses different Q4/Q8 packages/phonemizers. "
            "Buffered WAV completion, not browser playback or streaming first-audio latency. "
            "Images share the exact bundled quantized checkpoint; embedded and external source revisions differ. "
            "Single order, no OS-cache flush, sampled resource measurements.",
        },
    ) as report:
        for arm in args.arms:
            paths = RunPaths(run.root / arm)
            paths.create()
            result = run_arm(args.kind, arm, paths, context, args.samples, deadline, args.with_chat)
            report.results.append(result)
            report.save(run)
            if result["status"] != "completed":
                report.status = "failed"
                raise RuntimeError(result["error"])
        inputs: dict[str, str | Path] = {}
        frameworks = set()
        for arm in args.arms:
            if args.kind == "tts":
                frameworks.add("koboldcpp" if arm == "internal" else "audiocpp")
                model = cfg.KOKORO_TTS.koboldcpp_model if arm == "internal" else cfg.KOKORO_TTS.audiocpp_model
                inputs["speech" if len(args.arms) == 1 else f"{arm}-speech"] = Path(model)
            else:
                frameworks.add("koboldcpp" if arm == "internal" else "sdcpp")
                inputs["image"] = Path(cfg.SDCPP_MODELS["nova3d-q4"])
        if args.with_chat:
            frameworks.add("koboldcpp")
            inputs["chat"] = Path(cfg.KOBOLDCPP_MODELS["llamacpp/gemma-4-E4B-it-Q4_0"])
            inputs["whisper"] = Path(str(cfg.KOBOLDCPP_KCPPS_ARGS["whispermodel"]))
        reporting.record_inputs(report, frameworks=tuple(sorted(frameworks)), models=inputs)
    write_summary(run, args.kind)


if __name__ == "__main__":
    main()
