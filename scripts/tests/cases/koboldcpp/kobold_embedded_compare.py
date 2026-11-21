"""Bounded Vulkan image comparison of KoboldCpp's embedded sd.cpp and the external sd-server."""

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
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests

from scripts.benchmarks.shared import reporting
from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.sdcpp import server as sdcpp
from scripts.shared.backends import listening
from scripts.shared.resources import summarize_resources, watch_resources
from scripts.tests.shared.paths import CasePaths, RunPaths

PORT = 18881
PROMPT = (
    "A small wooden cabin beside a calm mountain lake, pine trees, morning sunlight, detailed landscape, no people."
)
IMAGE = {"width": 512, "height": 512, "steps": 12, "cfg_scale": 4.0, "clip_skip": 2, "seed": 42}


def post(path: str, body: dict[str, Any], timeout: float, port: int = PORT) -> tuple[bytes, dict[str, Any]]:
    started = time.perf_counter()
    response = requests.post(f"http://127.0.0.1:{port}{path}", json=body, timeout=timeout, stream=True)
    with response:
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:2000]}")
        first = response.raw.read(4096)
        first_seconds = time.perf_counter() - started
        data = first + response.raw.read()
        content_type = response.headers.get("Content-Type")
    return data, {
        "seconds": time.perf_counter() - started,
        "first_body_seconds": first_seconds,
        "content_type": content_type,
        "response_bytes": len(data),
    }


def sample(arm: str, index: int, paths: RunPaths, deadline: float) -> dict[str, Any]:
    timeout = min(90, deadline - time.monotonic())
    if timeout <= 0:
        raise TimeoutError("Whole-run budget exhausted")
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
    destination = paths.artifacts / ("warmup" if index < 0 else f"sample-{index}")
    destination = destination.with_suffix(".png")
    destination.write_bytes(data)
    result.update(file=str(destination), request=body, sha256=hashlib.sha256(data).hexdigest())
    return result


def command(arm: str) -> list[str]:
    if arm == "internal":
        return [
            str(cfg.KOBOLDCPP_SERVICE.exe),
            "--nomodel",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--usevulkan",
            "0",
            "--sdmodel",
            cfg.SDCPP_MODELS["nova3d-q4"],
            "--sdthreads",
            str(cfg.AUDIOCPP_SPEECH.threads),
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
        str(cfg.AUDIOCPP_SPEECH.threads),
        "--diffusion-fa",
    ]


def wait_ready(process: subprocess.Popen[Any], deadline: float, port: int = PORT) -> None:
    from scripts.shared.wait import http_ready
    from scripts.shared.wait import wait_ready as shared_wait

    shared_wait(
        lambda: http_ready(f"http://127.0.0.1:{port}/v1/models"),
        max(0.0, deadline - time.monotonic()),
        label=f"Kobold on port {port}",
        process=process,
        interval=0.25,
    )


def run_arm(arm: str, paths: RunPaths, context: dict[str, Any], count: int, deadline: float) -> dict[str, Any]:
    cmd = command(arm)
    result: dict[str, Any] = {"arm": arm, "command": cmd, "samples": [], "status": "running"}
    model = Path(cfg.SDCPP_MODELS["nova3d-q4"])
    with model.open("rb") as source:
        result["model"] = {
            "path": str(model),
            "bytes": model.stat().st_size,
            "sha256": hashlib.file_digest(source, "sha256").hexdigest(),
        }
    result["version"] = subprocess.check_output(
        [cmd[0], "--version"], text=True, encoding="utf-8", errors="replace"
    ).strip()
    env = os.environ.copy()
    env.update(
        TEMP=str(cfg.LAUNCH.temp_dir), TMP=str(cfg.LAUNCH.temp_dir), OMP_NUM_THREADS=str(cfg.AUDIOCPP_SPEECH.threads)
    )
    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    env["PATH"] = str(Path(cmd[0]).parent) + os.pathsep + env.get("PATH", "")
    samples, stop = [], threading.Event()
    started = time.perf_counter()
    with (paths.logs / "server.log").open("wb") as log, BenchmarkVram(paths, context) as memory:
        process = subprocess.Popen(cmd, cwd=project_cfg.BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
        launch_util.assign_process_to_job(process.pid)
        watcher = None
        try:
            wait_ready(process, min(deadline, time.monotonic() + 60))
            result["startup_seconds"] = time.perf_counter() - started
            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:image:{arm}" if process.poll() is None else "")
            lifecycle.adopt_prepared(result["startup_seconds"])
            import psutil

            children = psutil.Process(process.pid).children(recursive=True)
            workers = [child for child in children if child.name().lower() == Path(cmd[0]).name.lower()]
            resource_pid = workers[-1].pid if workers else process.pid
            result["resource_pid"] = resource_pid
            memory.watch_backend(arm, [resource_pid])
            watched = SimpleNamespace(pid=resource_pid, poll=process.poll)
            watcher = threading.Thread(
                target=watch_resources,
                args=(watched, stop, samples, deadline, lambda: memory.stage, started),
                daemon=True,
            )
            watcher.start()
            memory.stage = "warmup"
            lifecycle.warmup(lambda: result.update(warmup=sample(arm, -1, paths, deadline)), includes_model_load=True)
            memory.stage = "measured"
            for index in range(count):
                row, timing = lifecycle.measure(lambda: sample(arm, index, paths, deadline))
                row.update(timing)
                result["samples"].append(row)
                print(f"[{arm}] {index + 1}/{count}: {row['seconds']:.3f}s", flush=True)
            result["median_seconds"] = statistics.median(row["seconds"] for row in result["samples"])
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


def write_summary(run: RunPaths) -> None:
    rows = []
    for arm in ("internal", "external"):
        path = run.root / arm / "artifacts" / "results.json"
        if not path.is_file():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["status"] != "completed":
            continue
        ram = result["resources"]["phases"]["measured"]["process_rss_bytes"]["maximum"] / 2**30
        memory = json.loads((path.parent / "vram.json").read_text(encoding="utf-8"))
        peak = memory["adapter"]["stage_peaks"].get("measured", {}).get("total_used_mb")
        peak_text = f"{peak / 1024:.2f}" if peak is not None else "unavailable"
        rows.append(f"| {arm} | {result['median_seconds']:.3f} | {peak_text} | {ram:.2f} |")
    header = (
        "| Engine | Median image seconds | Sampled adapter peak GiB | Sampled process peak GiB |\n|---|---:|---:|---:|"
    )
    text = f"# Embedded versus external image\n\n{header}\n" + "\n".join(rows)
    text += (
        "\n\n- Whole-adapter GPU usage includes desktop/other allocations; peaks are sampled lower bounds.\n"
        "- Server workers are sampled after readiness, including Kobold's extracted child executable.\n"
        "- Images: identical quantized checkpoint, Vulkan, 512x512, 12 Euler A steps, CFG 4, CLIP skip 2, seed 42, ETA "
        "1. "
        "One prompt/resolution does not establish general image performance or quality.\n"
        "- Commands, versions, model hashes, requests and resource traces are saved beside each arm.\n"
        "- Compare internal/artifacts/sample-0 and external/artifacts/sample-0 for matching media.\n"
    )
    (run.artifacts / "comparison.md").write_text(text, encoding="utf-8")
    if all((run.root / arm / "artifacts/sample-0.png").is_file() for arm in ("internal", "external")):
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
    parser.add_argument("--arms", nargs="+", choices=("internal", "external"), default=["internal", "external"])
    parser.add_argument("--repeats", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    context = dict(require_native_execution("Embedded/external image comparison"))
    import psutil

    native_names = {"koboldcpp-nocuda.exe", "koboldcpp.exe", "audiocpp_server.exe", "sd-server.exe", "llama-server.exe"}
    active = [p.info["name"] for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() in native_names]
    if active:
        raise RuntimeError(f"Existing native sessions detected: {active}; no service was stopped")
    if listening(PORT):
        raise RuntimeError(f"Port {PORT} is occupied; existing service was not changed")
    run = CasePaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    deadline = time.monotonic() + 240
    with report_run(
        run,
        "koboldcpp/kobold_embedded_compare",
        "image",
        settings={
            "kind": "image",
            "execution_context": context,
            "samples": args.repeats,
            "image": IMAGE,
            "limits": "Images share the exact bundled quantized checkpoint; embedded and external source revisions "
            "differ. Single order, no OS-cache flush, sampled resource measurements.",
        },
    ) as report:
        for arm in args.arms:
            paths = RunPaths(run.root / arm)
            paths.create()
            result = run_arm(arm, paths, context, args.repeats, deadline)
            report.results.append(result)
            report.save(run)
            if result["status"] != "completed":
                report.status = "failed"
                raise RuntimeError(result["error"])
        frameworks = {"koboldcpp" if arm == "internal" else "sdcpp" for arm in args.arms}
        reporting.record_inputs(
            report, frameworks=tuple(sorted(frameworks)), models={"image": Path(cfg.SDCPP_MODELS["nova3d-q4"])}
        )
    write_summary(run)


if __name__ == "__main__":
    main()
