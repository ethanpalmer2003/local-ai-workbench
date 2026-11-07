"""Bounded same-release sd.cpp ROCm/Vulkan server comparison."""

import base64
import hashlib
import io
import json
import os
import statistics
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.backend_readiness import ready_url
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.sdcpp import server as sdcpp
from scripts.tests.shared import benchmark_config as benchmark_cfg
from scripts.tests.shared.backends import listening
from scripts.tests.shared.resources import summarize_resources, watch_resources

PORT = 18889
PROMPT = (
    "A small wooden cabin beside a calm mountain lake, pine trees, morning sunlight, detailed landscape, no people."
)


def request_body(prompt: str = PROMPT) -> dict[str, Any]:
    defaults = cfg.SDCPP_REQUEST_DEFAULTS
    native = {
        "negative_prompt": defaults["negative_prompt"],
        "clip_skip": defaults["clip_skip"],
        "seed": 42,
        "sample_params": {
            "sample_method": defaults["sampler_name"],
            "sample_steps": defaults["steps"],
            "guidance": {"txt_cfg": defaults["cfg_scale"]},
        },
    }
    return {
        "prompt": prompt + " <sd_cpp_extra_args>" + json.dumps(native) + "</sd_cpp_extra_args>",
        "size": f"{defaults['width']}x{defaults['height']}",
        "n": 1,
        "response_format": "b64_json",
    }


def image_request(body: dict[str, Any], path, timeout: float) -> dict[str, Any]:
    from PIL import Image

    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/images/generations",
        json.dumps(body).encode(),
        {"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    seconds = time.perf_counter() - start
    image = base64.b64decode(payload["data"][0]["b64_json"], validate=True)
    with Image.open(io.BytesIO(image)) as picture:
        picture.load()
        dimensions = picture.size
        if dimensions != (cfg.SDCPP_REQUEST_DEFAULTS["width"], cfg.SDCPP_REQUEST_DEFAULTS["height"]):
            raise ValueError(f"Unexpected image size: {dimensions}")
    path.write_bytes(image)
    return {
        "seconds": seconds,
        "dimensions": dimensions,
        "image": str(path),
        "sha256": hashlib.sha256(image).hexdigest(),
    }


def _launch_context(build: str, extra_args: tuple[str, ...]) -> tuple[Path, list[str], dict[str, str]]:
    """Return the build directory, server command and environment for one backend."""
    directory = sdcpp.build_dir(build)
    command = [
        str(directory / "sd-server.exe"),
        *launch_util.build_cli_args(cfg.SDCPP_SERVER_ARGS),
        "--listen-ip",
        "127.0.0.1",
        "--listen-port",
        str(PORT),
        "--rng",
        "cpu",
        "--threads",
        "8",
        *extra_args,
    ]
    env = os.environ.copy()
    env["PATH"] = str(directory) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONHOME", None)
    return directory, command, env


def _await_ready(process: subprocess.Popen[bytes], deadline: float) -> None:
    """Wait for the server to answer readiness; raise on early exit or startup timeout."""
    ready_deadline = min(deadline, time.monotonic() + 90)
    while time.monotonic() < ready_deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited: {process.returncode}")
        try:
            with urllib.request.urlopen(ready_url("sdcpp", PORT), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        raise TimeoutError("Server startup exceeded 90 seconds")


def _finalize_resources(
    result: dict[str, Any], samples: list[dict[str, Any]], output: RunPaths, started: float
) -> None:
    """Fold the sampled RAM rows and the total runtime into the run result."""
    result["ram"] = {
        "minimum_available_gib": min((s["available_gib"] for s in samples), default=None),
        "peak_process_rss_bytes": max((s["process_rss_bytes"] or 0 for s in samples), default=None),
        "aborted": any(s.get("abort") for s in samples),
    }
    result["resources"] = summarize_resources(samples)
    (output.logs / "resources.json").write_text(json.dumps(samples, indent=2))
    result["total_seconds"] = time.perf_counter() - started


def arm(
    build: str,
    output: RunPaths,
    context: dict[str, Any],
    deadline: float,
    extra_args: tuple[str, ...] = (),
    fresh_prompts: bool = False,
    fast_adapter_sampling: bool = False,
) -> dict[str, Any]:
    directory, command, env = _launch_context(build, extra_args)
    result: dict[str, Any] = {
        "build": build,
        "command": command,
        "release_asset": (directory / ".release_asset").read_text().strip(),
        "version": subprocess.check_output([str(directory / "sd-cli.exe"), "--version"], text=True).strip(),
        "samples": [],
        "status": "running",
        "guards": {"minimum_free_ram_gib": benchmark_cfg.MINIMUM_FREE_RAM_GIB},
    }
    samples, stop = [], threading.Event()
    started = time.perf_counter()
    with (
        (output.logs / "server.log").open("wb") as log,
        BenchmarkVram(output, context, fast_adapter_sampling=fast_adapter_sampling) as vram,
    ):
        process = subprocess.Popen(command, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT)
        watcher = threading.Thread(
            target=watch_resources, args=(process, stop, samples, deadline, lambda: vram.stage, started), daemon=True
        )
        watcher.start()
        try:
            vram.watch_backend(build, [process.pid])
            _await_ready(process, deadline)
            result["startup_seconds"] = time.perf_counter() - started
            from scripts.benchmarks.shared.benchmark import BenchmarkLifecycle

            lifecycle = BenchmarkLifecycle(lambda: f"{process.pid}:{build}" if process.poll() is None else "")
            lifecycle.adopt_prepared(result["startup_seconds"])
            body = request_body(PROMPT + " Warmup view: sunset." if fresh_prompts else PROMPT)
            result["request"] = body
            vram.stage = "warmup"
            lifecycle.warmup(
                lambda: result.update(
                    warmup=image_request(body, output.artifacts / "warmup.png", min(150, deadline - time.monotonic()))
                ),
                includes_model_load=True,
            )
            vram.stage = "measured"
            for index in range(2):
                body = request_body(PROMPT + f" View {index + 1}: gentle clouds." if fresh_prompts else PROMPT)
                row, timing = lifecycle.measure(
                    lambda: image_request(
                        body, output.artifacts / f"image-{index}.png", min(150, deadline - time.monotonic())
                    )
                )
                row.update(timing)
                row["request"] = body
                result["samples"].append(row)
                print(f"[{build}] measured {index + 1}/2: {row['seconds']:.2f}s", flush=True)
            result["median_seconds"] = statistics.median(row["seconds"] for row in result["samples"])
            result["status"] = "completed"
            result["benchmark"] = lifecycle.record()
        except Exception as error:
            result["status"], result["error"] = "failed", str(error)
        finally:
            vram.stage = "cleanup"
            stop.set()
            watcher.join(timeout=5)
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
            process.wait(timeout=15)
            _finalize_resources(result, samples, output, started)
    (output.artifacts / "results.json").write_text(json.dumps(result, indent=2))
    return result


def preflight() -> dict[str, Any]:
    import psutil

    context = dict(require_native_execution("sd.cpp backend comparison"))
    if launch_util.llama_server_running() or any(listening(p) for p in (1234, 1235, PORT)):
        raise RuntimeError("Existing backend detected; no process stopped")
    names = {
        "sd-cli.exe",
        "sd-server.exe",
        "strata.exe",
        "audiocpp_server.exe",
        "koboldcpp.exe",
        "koboldcpp-nocuda.exe",
    }
    if any((p.info["name"] or "").lower() in names for p in psutil.process_iter(["name"])):
        raise RuntimeError("Existing native model process detected; no process stopped")
    return context


def main():
    context = preflight()
    output = BenchmarkPaths(__file__).new_run()
    print(f"[OUTPUT] {output.root}", flush=True)
    deadline = time.monotonic() + 480
    with report_run(
        output,
        "sdcpp/sdcpp_backend_compare",
        "image",
        settings={
            "execution_context": context,
            "seed": 42,
            "rng": "cpu",
            "threads": 8,
            "repetitions": 2,
            "controls": "same model, native server args, prompt, seed, sampler, steps, dimensions; full-workload warmup",
            "limits": "single ROCm-then-Vulkan order; OS caches not reset; sampled RAM/VRAM; no broad image-quality claim",
        },
    ) as report:
        for build in ("rocm", "vulkan"):
            folder = RunPaths(output.root / build)
            folder.create()
            result = arm(build, folder, context, deadline)
            report.results.append(result)
            report.save(output)
            if result["status"] != "completed":
                report.status = "failed"
                raise RuntimeError(f"{build} failed; inspect saved logs before continuing")
    print(f"[RESULTS] {output.artifacts}", flush=True)


if __name__ == "__main__":
    main()
