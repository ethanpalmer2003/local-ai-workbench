"""Compare ComfyUI launcher presets and local LTX 2.5 models with the saved I2V workflow."""

import argparse
import asyncio
import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.benchmark import workflow_timing
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.benchmarks.shared.reporting import report_run, write_results
from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.comfyui.workflow_overrides import LTXWorkflowOverrides, VAEDecode, VideoVAE, workflow
from scripts.launchers.runtime import gpu_memory

MODELS = (model_cfg.path("comfyui/LTX25-distilled-DiT-Q3_K_M").name,)
ENCODERS = (
    model_cfg.path("comfyui/gemma4-12b-with-proj-ltx-2.5-Q2_K").name,
    model_cfg.path("comfyui/gemma4-12b-with-proj-ltx-2.5-Q4_K_M").name,
)
PRESETS = ("user",)
LAUNCH_CASES = ("baseline", "smart-on", "autotune-off", "triton-on", "dynamic-off", "pinned-on")


def tile_cases(group: str) -> tuple[tuple[str, LTXWorkflowOverrides], ...]:
    cases = []
    if group in {"all", "spatial"}:
        for resolution in (480, 640):
            for spatial, overlap in ((512, 64), (768, 192), (1024, 256)):
                cases.append(
                    (
                        f"spatial-r{resolution}-s{spatial}-o{overlap}",
                        LTXWorkflowOverrides(
                            seconds=5,
                            fps=24,
                            resolution=resolution,
                            mode=2,
                            spatial_tile=spatial,
                            spatial_overlap=overlap,
                            temporal_tile=128,
                            temporal_overlap=32,
                            video_vae=VideoVAE.DIFFUSION,
                            vae_decode=VAEDecode.TILED,
                        ),
                    )
                )
    if group in {"all", "temporal"}:
        for temporal, overlap in ((64, 16), (128, 32), (192, 48)):
            cases.append(
                (
                    f"temporal-t{temporal}-o{overlap}",
                    LTXWorkflowOverrides(
                        seconds=10,
                        fps=24,
                        resolution=480,
                        mode=2,
                        spatial_tile=512,
                        spatial_overlap=64,
                        temporal_tile=temporal,
                        temporal_overlap=overlap,
                        video_vae=VideoVAE.DIFFUSION,
                        vae_decode=VAEDecode.TILED,
                    ),
                )
            )
    return tuple(cases)


# - one wrapper carries the launch settings; its `set "NAME=value"` lines decide the flags
WRAPPERS = {"user": "launch_comfyui.bat"}


def launch_options(preset: str) -> tuple[list[str], dict[str, str]]:
    wrapper = project_cfg.BAT_DIR / "browser/comfyui" / WRAPPERS.get(preset, "launch_comfyui.bat")
    settings = dict(re.findall(r'(?m)^[ \t]*set "([A-Z_0-9]+)=([^"\r\n]*)"', wrapper.read_text(encoding="utf-8")))
    flags = ["--disable-partner-nodes", "--disable-pinned-memory", "--enable-manager", "--enable-manager-legacy-ui"]
    for setting, on, off in (
        ("DISABLE_TRITON", "--disable-triton-backend", "--enable-triton-backend"),
        ("DYNAMIC_VRAM", "--enable-dynamic-vram", "--disable-dynamic-vram"),
    ):
        if settings.get(setting) in {"0", "1"}:
            flags.append(on if settings[setting] == "1" else off)
    if "ATTENTION" in settings:
        flags.append(
            {
                "sage": "--use-sage-attention",
                "flash": "--use-flash-attention",
                "pytorch": "--use-pytorch-cross-attention",
            }[settings["ATTENTION"]]
        )
    if "CACHE_MODE" in settings:
        flags.append({"none": "--cache-none", "ram": "--cache-ram"}[settings["CACHE_MODE"]])
    if settings.get("SMART_MEMORY") == "0":
        flags.append("--disable-smart-memory")
    env = {
        "COMFYUI_ENABLE_MIOPEN": "0",
        "FLASH_ATTENTION_TRITON_AMD_ENABLE": "TRUE",
        "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": "1",
        "MIOPEN_FIND_ENFORCE": "1",
        "MIOPEN_FIND_MODE": "2",
        "MIOPEN_DEBUG_DISABLE_FIND_DB": "0",
        "MIOPEN_SEARCH_CUTOFF": "1",
        "MIOPEN_ENABLE_LOGGING": "0",
        "MIOPEN_LOG_LEVEL": "0",
        "MIOPEN_ENABLE_LOGGING_CMD": "0",
        "TRITON_PRINT_AUTOTUNING": "0",
        "TRITON_CACHE_AUTOTUNING": "0",
        "PYTHONUTF8": "1",
        "PYTHONNOUSERSITE": "1",
    }
    if settings.get("FA_AUTOTUNE") in {"0", "1"}:
        env["FLASH_ATTENTION_TRITON_AMD_AUTOTUNE"] = "TRUE" if settings["FA_AUTOTUNE"] == "1" else "FALSE"
    return flags, env


def validation_options(case: str) -> tuple[list[str], dict[str, str]]:
    flags, env = launch_options("user")
    controlled = {
        "--disable-triton-backend",
        "--enable-triton-backend",
        "--enable-dynamic-vram",
        "--disable-dynamic-vram",
        "--disable-smart-memory",
        "--use-sage-attention",
        "--use-flash-attention",
        "--use-pytorch-cross-attention",
        "--cache-none",
        "--cache-ram",
    }
    flags = [flag for flag in flags if flag not in controlled]
    flags.extend(("--use-sage-attention", "--cache-none"))
    if case == "all-off-0000":
        flags.extend(("--disable-smart-memory", "--enable-triton-backend", "--disable-dynamic-vram"))
        env["FLASH_ATTENTION_TRITON_AMD_AUTOTUNE"] = "FALSE"
    elif case in {"all-on-1111", "smart-memory-off-0111"}:
        flags.extend(("--disable-triton-backend", "--enable-dynamic-vram"))
        env["FLASH_ATTENTION_TRITON_AMD_AUTOTUNE"] = "TRUE"
        if case == "smart-memory-off-0111":
            flags.append("--disable-smart-memory")
    else:
        raise ValueError(f"Unknown validation case: {case}")
    return flags, env


def isolated_launch_options(case: str) -> tuple[list[str], dict[str, str]]:
    flags, env = validation_options("smart-memory-off-0111")
    if case == "smart-on":
        flags.remove("--disable-smart-memory")
    elif case == "autotune-off":
        env["FLASH_ATTENTION_TRITON_AMD_AUTOTUNE"] = "FALSE"
    elif case == "triton-on":
        flags[flags.index("--disable-triton-backend")] = "--enable-triton-backend"
    elif case == "dynamic-off":
        flags[flags.index("--enable-dynamic-vram")] = "--disable-dynamic-vram"
    elif case == "pinned-on":
        # - the wrapper disables pinned memory unconditionally; this case is the only way to compare it
        if "--disable-pinned-memory" in flags:
            flags.remove("--disable-pinned-memory")
    elif case != "baseline":
        raise ValueError(f"Unknown launch case: {case}")
    return flags, env


def check_ports(port: int) -> None:
    for candidate in {8188, port}:
        with socket.socket() as connection:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                connection.bind(("127.0.0.1", candidate))
            except OSError as error:
                raise RuntimeError(f"Cannot reserve localhost port {candidate}: {error}") from error


async def wait_ready(session: Any, base: str, process: subprocess.Popen[bytes]) -> dict[str, Any]:
    import aiohttp

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"ComfyUI exited with code {process.returncode}; inspect the server log")
        try:
            async with session.get(base + "/object_info", timeout=aiohttp.ClientTimeout(total=3)) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientConnectionError, TimeoutError) as error:
            if isinstance(error.__cause__, OSError) and getattr(error.__cause__, "winerror", None) == 10013:
                raise
            await asyncio.sleep(1)
    raise TimeoutError("ComfyUI startup exceeded 180 seconds")


async def _submit_prompt(session: Any, base: str, graph: dict[str, Any], client: str) -> str:
    async with session.post(base + "/prompt", json={"prompt": graph, "client_id": client}) as response:
        submitted = await response.json()
        if response.status != 200:
            raise RuntimeError(f"Workflow rejected: {submitted}")
    return submitted["prompt_id"]


class _StageTracker:
    """Per-node durations accumulated from ComfyUI `executing` events."""

    def __init__(self) -> None:
        self.active: str | None = None
        self.started = 0.0
        self.stages: dict[str, float] = {}

    def executing(self, data: dict[str, Any], now: float, graph: dict[str, Any], bar: Any, monitor: Any) -> bool:
        """Charge the previous node, describe the new one, and report whether execution ended."""
        if self.active is not None:
            self.stages[self.active] = self.stages.get(self.active, 0) + now - self.started
        self.active = data["node"]
        if monitor is not None:
            monitor.stage = "complete" if self.active is None else graph[str(self.active)]["class_type"]
        self.started = now
        if self.active is None:
            return True
        bar.set_description(graph[str(self.active)]["class_type"])
        return False


async def _consume_events(
    ws: Any,
    log: Any,
    bar: Any,
    graph: dict[str, Any],
    prompt_id: str,
    timeout: float,
    started: float,
    monitor: gpu_memory.GpuMemoryMonitor | None,
) -> dict[str, float]:
    import aiohttp

    tracker = _StageTracker()
    tracker.started = started
    async with asyncio.timeout(timeout):
        while True:
            message = await ws.receive(timeout=timeout)
            if message.type == aiohttp.WSMsgType.BINARY:
                continue
            if message.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError(f"ComfyUI websocket closed: {message.type}")
            event = json.loads(message.data)
            data = event.get("data", {})
            if data.get("prompt_id") not in (None, prompt_id):
                continue
            now = time.monotonic()
            log.write(json.dumps({"seconds": now - started, **event}) + "\n")
            log.flush()
            if event["type"] in {"execution_error", "execution_interrupted"}:
                raise RuntimeError(f"ComfyUI execution failed: {data}")
            if event["type"] == "executing" and tracker.executing(data, now, graph, bar, monitor):
                break
            if event["type"] == "progress" and str(data.get("node", tracker.active)) == "18":
                bar.total = data["max"]
                bar.update(max(0, data["value"] - bar.n))
    return tracker.stages


async def _fetch_history(session: Any, base: str, prompt_id: str) -> dict[str, Any]:
    async with session.get(base + "/history/" + prompt_id) as response:
        response.raise_for_status()
        return await response.json()


async def generate(
    session: Any,
    base: str,
    graph: dict[str, Any],
    paths: RunPaths,
    label: str,
    timeout: float,
    monitor: gpu_memory.GpuMemoryMonitor | None = None,
) -> dict[str, Any]:
    from tqdm import tqdm

    client = uuid.uuid4().hex
    events = paths.logs / f"{label}-events.jsonl"
    started = time.monotonic()
    async with session.ws_connect(base + "/ws?clientId=" + client, max_msg_size=32 * 1024 * 1024) as ws:
        prompt_id = await _submit_prompt(session, base, graph, client)
        with (
            events.open("w", encoding="utf-8") as log,
            tqdm(total=8, desc="Sampling", ascii=True, unit="step", position=1, leave=False) as bar,
        ):
            stages = await _consume_events(ws, log, bar, graph, prompt_id, timeout, started, monitor)
    history = await _fetch_history(session, base, prompt_id)
    (paths.artifacts / f"{label}-history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    entry = history[prompt_id]
    if entry["status"]["status_str"] != "success" or not entry["outputs"]:
        raise RuntimeError(f"No successful video output: {entry}")
    return {
        "label": label,
        "seconds": time.monotonic() - started,
        "sampler_seconds": stages.get("18"),
        "video_decode_seconds": sum(
            stages.get(key, 0) for key, node in graph.items() if node["class_type"] in {"VAEDecode", "VAEDecodeTiled"}
        ),
        "node_seconds": stages,
        "outputs": entry["outputs"],
    }


def _workflow_vaes(saved: dict[str, Any], selected_vae: str | None) -> tuple[str, ...]:
    vaes = tuple(
        node["widgets_values_named"]["vae_name"]
        for node in saved["nodes"]
        if node["type"] == "VAELoader" and node.get("mode", 0) == 0 and (node["id"] != 4 or selected_vae is None)
    )
    if selected_vae is not None:
        vaes += (selected_vae,)
    return vaes


def _require_model_files(model_root: Path, groups: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    for folder, names in groups:
        for filename in names:
            if not (model_root / folder / filename).is_file():
                raise FileNotFoundError(model_root / folder / filename)


def _stage_source(name: str, saved: dict[str, Any], comfy: Path, paths: RunPaths) -> None:
    (paths.artifacts / f"source-{name}.json").write_text(json.dumps(saved, indent=2), encoding="utf-8")
    for node in saved["nodes"]:
        if node["type"] == "LoadImage" and node.get("mode", 0) == 0:
            image_name = node["widgets_values_named"]["image"]
            source_image = comfy / "input" / image_name
            target_image = paths.temp / image_name
            target_image.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_image, target_image)


def _select_sources(
    args: argparse.Namespace, comfy: Path, model_root: Path, paths: RunPaths
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], dict[str, Any], dict[str, Any]]:
    models = MODELS if args.model == "all" else (MODELS[int(args.model) - 1],)
    encoders = ENCODERS if args.encoder == "all" else (ENCODERS[int(args.encoder) - 1],)
    presets = PRESETS if args.preset == "all" else (args.preset,)
    if args.validate_findings:
        presets = ("all-on-1111", "smart-memory-off-0111", "all-off-0000")
    sources = {"selected": args.workflow}
    if args.compare_workflows:
        presets = ("original", "default")
        sources = {"original": args.workflow, "default": comfy / "user/default/workflows/video_ltx2_5_i2v_default.json"}
    saved_workflows = {name: json.loads(source.read_text(encoding="utf-8")) for name, source in sources.items()}
    selected_vae = LTXWorkflowOverrides(video_vae=VideoVAE(args.video_vae)).video_vae_filename
    for name, saved in saved_workflows.items():
        vaes = _workflow_vaes(saved, selected_vae)
        _require_model_files(model_root, (("unet", models), ("clip", encoders), ("vae", vaes)))
        _stage_source(name, saved, comfy, paths)
    return models, encoders, presets, sources, saved_workflows


def _workload_cases(args: argparse.Namespace, paths: RunPaths) -> tuple[tuple[str, LTXWorkflowOverrides], ...]:
    cases = (
        tile_cases(args.tile_sweep)
        if args.tile_sweep
        else (
            (
                "saved",
                LTXWorkflowOverrides(
                    seconds=args.seconds,
                    fps=args.fps,
                    resolution=args.resolution,
                    mode=args.mode,
                    spatial_tile=args.spatial_tile,
                    spatial_overlap=args.spatial_overlap,
                    temporal_tile=args.temporal_tile,
                    temporal_overlap=args.temporal_overlap,
                    video_vae=VideoVAE(args.video_vae),
                    vae_decode=VAEDecode(args.vae_decode),
                ),
            ),
        )
    )
    if args.tile_sweep:
        matrix = [{"name": name, "settings": asdict(settings)} for name, settings in cases]
        (paths.artifacts / "tile-matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
        print(
            f"[PLAN] {len(cases)} tile configurations; {len(cases) * args.repeat} clips; original VAE only", flush=True
        )
    return cases


def _configuration_label(args: argparse.Namespace, preset: str, model: str, encoder: str, case_name: str) -> str:
    label = f"{preset}-m{MODELS.index(model) + 1}-e{ENCODERS.index(encoder) + 1}"
    if args.tile_sweep:
        label += f"-{case_name}"
    return label


def _server_command(args: argparse.Namespace, python: Path, paths: RunPaths, flags: list[str]) -> list[str]:
    return [
        str(python),
        "main.py",
        *flags,
        "--listen",
        "127.0.0.1",
        "--port",
        str(args.port),
        "--disable-auto-launch",
        "--input-directory",
        str(paths.temp),
        "--output-directory",
        str(paths.artifacts / "videos"),
        "--temp-directory",
        str(paths.temp / "comfy"),
    ]


def _align_reference_graph(graph: dict[str, Any], original: dict[str, Any], settings: LTXWorkflowOverrides) -> None:
    reference = workflow(original, settings)
    for key in ("46", "47"):
        if reference[key]["inputs"]["value"] != 1:
            raise ValueError("Workflow comparison requires baseline video/audio CFG 1")
    shared = (1, 2, 35, 14, 15, 17, 40, 41, 42, 45, 48, 49, 54, 55, 56, 57, 58, 59, 60, 61, 62)
    for key in map(str, shared):
        graph[key]["inputs"] = dict(reference[key]["inputs"])
    graph["6"]["inputs"]["text"] = reference["6"]["inputs"]["text"]


def _launch_plan(
    args: argparse.Namespace,
    preset: str,
    label: str,
    model: str,
    encoder: str,
    case_name: str,
    python: Path,
    paths: RunPaths,
    case_settings: LTXWorkflowOverrides,
    saved: dict[str, Any],
    source: Any,
    saved_workflows: dict[str, Any],
) -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, str]]:
    if args.launch_case:
        flags, overrides = isolated_launch_options(args.launch_case)
    elif args.compare_workflows or args.tile_sweep:
        flags, overrides = validation_options("smart-memory-off-0111")
    else:
        flags, overrides = validation_options(preset) if args.validate_findings else launch_options(preset)
    command = _server_command(args, python, paths, flags)
    settings = replace(
        case_settings,
        model=model,
        encoder=encoder,
        prefix=label,
        dynamic_vram=False if "--disable-dynamic-vram" in flags else True if "--enable-dynamic-vram" in flags else None,
    )
    graph = workflow(saved, settings)
    if args.compare_workflows and preset == "default":
        _align_reference_graph(graph, saved_workflows["original"], settings)
    (paths.artifacts / f"{label}-prompt.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
    metadata = {
        "preset": preset,
        "launch_case": args.launch_case,
        "model": model,
        "encoder": encoder,
        "command": command,
        "environment": overrides,
        "vae_decode": settings.vae_decode,
        "tile_case": case_name if args.tile_sweep else None,
        "workflow_overrides": asdict(settings),
        "effective_settings": settings.effective_settings(graph, saved["extra"]["benchmark_controls"]),
        "workflow": str(source),
    }
    (paths.artifacts / f"{label}-launch.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return command, graph, metadata, overrides


def _server_env(python: Path, comfy: Path, overrides: dict[str, str]) -> dict[str, str]:
    env = {
        **os.environ,
        **overrides,
        "PYTORCH_TUNABLEOP_CACHE_DIR": str(comfy / "tunableop-cache"),
        "TRITON_CACHE_DIR": str(comfy / "triton-cache"),
    }
    env["PATH"] = str(python.parent) + os.pathsep + str(python.parent / "Scripts") + os.pathsep + env["PATH"]
    return env


def _rocm_sdk_env(comfy: Path, python: Path, env: dict[str, str], server_log: Any) -> None:
    subprocess.run(
        [str(python), "-m", "rocm_sdk", "init"],
        cwd=comfy,
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        check=True,
    )
    sdk = subprocess.check_output(
        [str(python), "-m", "rocm_sdk", "path", "--root"], cwd=comfy, env=env, text=True
    ).strip()
    env.update(HIP_PATH=sdk, ROCM_PATH=sdk)


def _launch_process(comfy: Path, command: list[str], env: dict[str, str], server_log: Any) -> subprocess.Popen[bytes]:
    return subprocess.Popen(command, cwd=comfy, env=env, stdout=server_log, stderr=subprocess.STDOUT)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


async def _generate_clips(
    args: argparse.Namespace,
    paths: RunPaths,
    results: list[dict[str, Any]],
    overall: Any,
    session: Any,
    base: str,
    process: subprocess.Popen[bytes],
    graph: dict[str, Any],
    metadata: dict[str, Any],
    startup: float,
    label: str,
) -> None:
    info = await wait_ready(session, base, process)
    (paths.artifacts / f"{label}-object-info.json").write_text(json.dumps(info), encoding="utf-8")
    missing = {n["class_type"] for n in graph.values()} - info.keys()
    if missing:
        raise RuntimeError(f"Missing ComfyUI nodes: {sorted(missing)}")
    startup_seconds = time.monotonic() - startup
    for repeat in range(args.repeat):
        clip_label = f"{label}-r{repeat + 1}"
        monitor = gpu_memory.GpuMemoryMonitor(
            process.pid, paths.logs / f"{clip_label}-vram.jsonl", enabled=not args.no_vram_monitor
        )
        try:
            with monitor:
                with workflow_timing() as timing:
                    result = await generate(session, base, graph, paths, clip_label, args.timeout, monitor)
                result.update(timing)
                if repeat == 0:
                    result["model_load_and_first_workflow_seconds"] = timing["workflow_seconds"]
        finally:
            vram = monitor.summary()
            (paths.artifacts / f"{clip_label}-vram.json").write_text(json.dumps(vram, indent=2), encoding="utf-8")
        result["vram"] = vram
        results.append({**metadata, **result, "startup_seconds": startup_seconds, "repeat": repeat + 1})
        write_results(paths, results)
        peak_mb = vram["peak_total_used_mb"]
        memory_note = (
            f"sampled GPU VRAM peak {peak_mb / 1024:.2f} GiB" if peak_mb is not None else f"VRAM {vram['status']}"
        )
        overall.write(
            f"[RESULT] {result['label']}: {result['seconds']:.2f}s; sampler {result['sampler_seconds']:.2f}s; {memory_note}"
        )
        overall.update(1)


async def _run_configuration(
    args: argparse.Namespace,
    paths: RunPaths,
    results: list[dict[str, Any]],
    overall: Any,
    comfy: Path,
    python: Path,
    base: str,
    saved_workflows: dict[str, Any],
    sources: dict[str, Any],
    preset: str,
    model: str,
    encoder: str,
    case_name: str,
    case_settings: LTXWorkflowOverrides,
) -> None:
    import aiohttp

    label = _configuration_label(args, preset, model, encoder, case_name)
    saved = saved_workflows[preset if args.compare_workflows else "selected"]
    source = sources[preset if args.compare_workflows else "selected"]
    command, graph, metadata, overrides = _launch_plan(
        args, preset, label, model, encoder, case_name, python, paths, case_settings, saved, source, saved_workflows
    )
    if args.dry_run:
        overall.update(args.repeat)
        return
    check_ports(args.port)
    env = _server_env(python, comfy, overrides)
    with (paths.logs / f"{label}-server.log").open("wb") as server_log:
        _rocm_sdk_env(comfy, python, env, server_log)
        startup = time.monotonic()
        process = _launch_process(comfy, command, env, server_log)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                await _generate_clips(
                    args, paths, results, overall, session, base, process, graph, metadata, startup, label
                )
        finally:
            _stop_process(process)
            check_ports(args.port)


async def benchmark(args: argparse.Namespace, paths: RunPaths, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from tqdm import tqdm

    comfy = project_cfg.FRAMEWORKS_DIR / "comfyui" / "rocm"
    python = comfy / "python_env/python.exe"
    model_root = project_cfg.DATA_DIR / "videogen"
    models, encoders, presets, sources, saved_workflows = _select_sources(args, comfy, model_root, paths)
    base = f"http://127.0.0.1:{args.port}"
    cases = _workload_cases(args, paths)
    with tqdm(
        total=len(presets) * len(models) * len(encoders) * len(cases) * args.repeat,
        desc="Configurations",
        ascii=True,
        unit="clip",
    ) as overall:
        for preset, model, encoder, (case_name, case_settings) in itertools.product(presets, models, encoders, cases):
            await _run_configuration(
                args,
                paths,
                results,
                overall,
                comfy,
                python,
                base,
                saved_workflows,
                sources,
                preset,
                model,
                encoder,
                case_name,
                case_settings,
            )
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow", type=Path, help="Defaults to the optimized workflow; comparison uses the baseline"
    )
    parser.add_argument(
        "--seconds", type=float, help="Override clip duration; rounded to the nearest supported interval"
    )
    parser.add_argument("--mode", type=int, choices=(1, 2, 3, 4), help="1 Preview, 2 Speed, 3 Quality, 4 Long")
    parser.add_argument("--fps", type=int, help="Override FPS for conditioning, audio and saved video")
    parser.add_argument("--resolution", type=int, help="Square-equivalent resolution, e.g. 480 -> 230400 target pixels")
    parser.add_argument("--preset", choices=("all", *PRESETS), default="all")
    parser.add_argument("--model", choices=("all", "1"), default="all")
    parser.add_argument("--encoder", choices=("all", "1", "2"), default="all")
    parser.add_argument("--repeat", type=int, help="Clips per fresh process (default: 1; validation: 2)")
    parser.add_argument("--vae-decode", choices=("saved", "tiled", "untiled"), default="saved")
    parser.add_argument("--video-vae", choices=("saved", "diffusion"), default="saved")
    parser.add_argument("--spatial-tile", type=int, help="Override spatial tile size")
    parser.add_argument("--spatial-overlap", type=int, help="Override spatial overlap")
    parser.add_argument("--temporal-tile", type=int, help="Override temporal tile size")
    parser.add_argument("--temporal-overlap", type=int, help="Override temporal overlap")
    parser.add_argument(
        "--validate-findings", action="store_true", help="Three-case 1111/0111/0000 comparison; encoder 1"
    )
    parser.add_argument(
        "--compare-workflows",
        action="store_true",
        help="Original versus default at fixed 0111; encoder 1, two clips each",
    )
    parser.add_argument(
        "--tile-sweep",
        nargs="?",
        const="all",
        choices=("all", "spatial", "temporal"),
        help="Original-VAE tile matrix: all 9, spatial 6, temporal 3 configurations; two clips each",
    )
    parser.add_argument("--port", type=int, default=8190)
    parser.add_argument("--timeout", type=float, default=900, help="Maximum seconds per clip")
    parser.add_argument("--dry-run", action="store_true", help="Write graphs/commands without launching or generating")
    parser.add_argument("--no-vram-monitor", action="store_true", help="Disable sampled OS VRAM monitoring")
    parser.add_argument("--launch-case", choices=LAUNCH_CASES, help="Fixed 0111 baseline or one isolated flag change")
    return parser


WORKLOAD_ARGUMENTS = (
    "seconds",
    "fps",
    "resolution",
    "mode",
    "spatial_tile",
    "spatial_overlap",
    "temporal_tile",
    "temporal_overlap",
)


def _resolve_tile_sweep(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.validate_findings or args.compare_workflows:
        parser.error("tile sweep cannot be combined with launcher/workflow comparisons")
    if args.vae_decode == "untiled":
        parser.error("tile sweep uses only the original VAE with tiled decoding")
    if any(getattr(args, name) is not None for name in WORKLOAD_ARGUMENTS):
        parser.error("tile sweep defines its own workloads and tiles; omit workload/tile overrides")
    if args.model not in {"all", "1"} or args.encoder not in {"all", "1"}:
        parser.error("tile sweep fixes model 1 and encoder 1")
    args.model, args.encoder, args.preset = "1", "1", "user"
    args.video_vae, args.vae_decode = "diffusion", "tiled"


def _resolve_repeat(args: argparse.Namespace) -> None:
    if args.repeat is None:
        args.repeat = 2 if args.validate_findings or args.compare_workflows or args.tile_sweep else 1


def _pin_single_model(args: argparse.Namespace) -> None:
    if not (args.validate_findings or args.compare_workflows):
        return
    if args.model == "all":
        args.model = "1"
    if args.encoder == "all":
        args.encoder = "1"


def _resolve_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.launch_case and (args.validate_findings or args.compare_workflows or args.tile_sweep):
        parser.error("launch-case cannot be combined with launcher/workflow/tile comparisons")
    if args.workflow is None:
        filename = "video_ltx2_5_i2v_original.json" if args.compare_workflows else "video_ltx2_5_i2v_default.json"
        args.workflow = project_cfg.FRAMEWORKS_DIR / "comfyui/rocm/user/default/workflows" / filename
    if args.tile_sweep:
        _resolve_tile_sweep(parser, args)
    if args.validate_findings and args.compare_workflows:
        parser.error("choose --validate-findings or --compare-workflows")
    _resolve_repeat(args)
    _pin_single_model(args)


def _validate_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.repeat < 1 or args.timeout <= 0:
        parser.error("repeat and timeout must be positive")
    if args.seconds is not None and args.seconds <= 0:
        parser.error("seconds must be positive")
    if args.fps is not None and not 1 <= args.fps <= 120:
        parser.error("fps must be between 1 and 120")
    if args.resolution is not None and args.resolution < 32:
        parser.error("resolution must be at least 32")
    for name in ("spatial_tile", "temporal_tile"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            parser.error(f"{name} must be positive")
    for name in ("spatial_overlap", "temporal_overlap"):
        value = getattr(args, name)
        if value is not None and value < 0:
            parser.error(f"{name} must be nonnegative")
    if args.vae_decode == "untiled" and any(
        getattr(args, name) is not None
        for name in ("spatial_tile", "spatial_overlap", "temporal_tile", "temporal_overlap")
    ):
        parser.error("tile overrides require tiled VAE decoding")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _resolve_arguments(parser, args)
    _validate_arguments(parser, args)
    paths = BenchmarkPaths(__file__).new_run()
    with report_run(
        paths, "ComfyUI LTX 2.5 video benchmark", "probes", settings={**vars(args), "workflow": str(args.workflow)}
    ) as report:
        print(f"[OUTPUT] {paths.root}", flush=True)
        asyncio.run(benchmark(args, paths, report.results))
        if args.dry_run:
            report.status = "dry-run"


if __name__ == "__main__":
    main()
