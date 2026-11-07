"""llama.cpp server for the KoboldCpp no-model UI, so chat runs on our own engine."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg

ALIAS = "character-external"


def no_model_config() -> Path:
    """KoboldCpp applies --config after the CLI, so the file itself must ask for no model."""
    data = json.loads(cfg.KOBOLDCPP_SERVICE.config.read_text(encoding="utf-8"))
    data.update({"nomodel": True, "model": [], "model_param": ""})
    folder = project_cfg.component("shared").cache_dir / "koboldcpp"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "no-model.kcpps"
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return target


def server_exe(build: str = "vulkan") -> Path:
    exe = cfg.LLAMACPP_BUILDS[build].bin_dir / "llama-server.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"llama.cpp server not found: {exe}")
    return exe


def model_path() -> Path:
    return cfg.KOBOLDCPP_MODELS[cfg.KOBOLDCPP_SERVICE.model]


def matching_options() -> dict[str, object]:
    """Mirror the KoboldCpp GPU settings so a comparison isolates the engine, not the offload."""
    from scripts.launchers.runtime import shared_gpu

    overrides = dict(cfg.KOBOLDCPP_MODEL_KCPPS_OVERRIDES.get(cfg.KOBOLDCPP_SERVICE.model) or {})
    overrides.update(shared_gpu.KOBOLDCPP_MODEL_ARGS.get(cfg.KOBOLDCPP_SERVICE.model) or {})
    return {
        "gpulayers": overrides.get("gpulayers", 99),
        "quantkv": cfg.KOBOLDCPP_KCPPS_ARGS.get("quantkv"),
        "contextsize": cfg.KOBOLDCPP_KCPPS_ARGS.get("contextsize"),
    }


def command(build: str = "vulkan") -> list[str]:
    options = matching_options()
    command = [
        str(server_exe(build)),
        "-m",
        str(model_path()),
        "--alias",
        ALIAS,
        "-c",
        str(options["contextsize"]),
        "-ngl",
        str(options["gpulayers"]),
        "-fa",
        "on",
    ]
    if options["quantkv"]:
        # - KoboldCpp's quantkv applies to K and V alike
        command += ["--cache-type-k", str(options["quantkv"]), "--cache-type-v", str(options["quantkv"])]
    return command + [
        # - carries the client's sampling and chat template, so Lite's settings still apply
        "--jinja",
        "--parallel",
        "1",
        # - Character turns rewrite early context; checkpoint reuse keeps most of the prefix
        "--cache-reuse",
        "256",
        "--host",
        str(cfg.LLAMACPP_SERVICE.listen_ip),
        "--port",
        str(cfg.LLAMACPP_SERVICE.internal_port),
    ]


def base_url() -> str:
    # - the backend sits on the +1 slot, so the public port keeps its usual proxy meaning
    return f"http://{cfg.LLAMACPP_SERVICE.listen_ip}:{cfg.LLAMACPP_SERVICE.internal_port}/v1"


def start(log_file: Path) -> subprocess.Popen[Any]:
    return launch_util.launch_process(
        command(),
        title="llama.cpp (Kobold no-model)",
        cwd=str(server_exe().parent),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log_file),
        report_vram=True,
        kill_ports=int(cfg.LLAMACPP_SERVICE.internal_port),
    )
