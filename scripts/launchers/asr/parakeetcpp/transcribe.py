"""File transcription with the maintained Parakeet.cpp CPU or Vulkan release."""

import argparse
import os
import subprocess
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution


def main() -> int:
    settings = cfg.PARAKEETCPP_ASR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input WAV file")
    parser.add_argument("--build", choices=("vulkan", "cpu"), default=settings.build)
    parser.add_argument("--profile", choices=("110m", "v3", "nemotron"), default="110m")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--stream", action="store_true", help="Stateful Nemotron file streaming; disables offline VAD")
    parser.add_argument("--language", default="auto", help="Nemotron language prompt")
    parser.add_argument("--vad-model", type=Path, default=settings.vad_model)
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.stream and args.profile != "nemotron":
        parser.error("--stream requires --profile nemotron")
    if args.stream and args.json:
        parser.error("--json is not supported with --stream by the installed CLI")
    if args.stream and args.build != "cpu":
        parser.error("Installed Vulkan Nemotron streaming crashes; use --build cpu for --stream")
    if args.language != "auto" and args.profile != "nemotron":
        parser.error("Explicit --language is configured only for Nemotron")
    selected = {
        "110m": settings.model,
        "v3": model_cfg.path("asr/parakeetcpp/parakeet-tdt-0.6b-v3-q8_0"),
        "nemotron": model_cfg.path("asr/parakeetcpp/nemotron-3.5-streaming-q8_0"),
    }
    args.model = args.model or selected[args.profile]
    exe = settings.executable(args.build)
    vad = settings.vad and not args.no_vad and not args.stream
    required = [exe, args.input, args.model, *([args.vad_model] if vad else [])]
    for path in required:
        if not path.is_file():
            parser.error(f"Missing file: {path}")
    command = [str(exe), "transcribe", "--model", str(args.model), "--input", str(args.input)]
    command += ["--threads", str(settings.threads)]
    if args.profile == "nemotron":
        command += ["--lang", args.language]
    if args.stream:
        command.append("--stream")
    if vad:
        command += ["--vad", "--vad-model", str(args.vad_model)]
    if args.timestamps:
        command.append("--timestamps")
    if args.json:
        command.append("--json")
    env = os.environ.copy()
    env["PARAKEET_DEVICE"] = "cpu" if args.build == "cpu" else settings.device
    require_native_execution("Parakeet ASR")
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
