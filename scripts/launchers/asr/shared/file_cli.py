"""Run a configured ASR file CLI; no automatic model downloads or server startup."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES, FileAsrProfile
from scripts.launchers.runtime.execution_context import require_native_execution


def required_files(profile: FileAsrProfile) -> tuple[Path, ...]:
    return (profile.executable, *(model_cfg.path(label) for label in profile.models))


def _validate_selection(key: str, profile: FileAsrProfile, selected: str, language: str, audio: Path | None) -> None:
    if selected not in profile.modes:
        raise ValueError(f"{key} supports these configured modes: {', '.join(profile.modes)}")
    if profile.languages and language.lower() not in profile.languages:
        raise ValueError(f"{key} accepts language selection: {', '.join(profile.languages)}")
    if selected != "live" and audio is None:
        raise ValueError("--input is required for file transcription")
    if selected == "live" and audio is not None:
        raise ValueError("--input and --mode live cannot be combined")


def _engine_arguments(profile: FileAsrProfile, selected: str, audio: Path | None, language: str) -> list[str]:
    executable = str((profile.mode_executables or {}).get(selected, profile.executable))
    arguments = [executable]
    for value in profile.arguments:
        if selected == "live" and value == "{input}":
            continue
        arguments.append(value.format(input=str(audio) if audio else "", language=language))
    return arguments + list(profile.modes[selected])


def _output_arguments(key: str, output: Path | None) -> list[str]:
    if output is None:
        return []
    if key == "nemo-speechcpp":
        return ["--output", str(output)]
    if key.startswith("audiocpp-"):
        return ["--text-out", str(output)]
    return []


def build_command(
    key: str, audio: Path | None, mode: str | None = None, language: str = "auto", output: Path | None = None
) -> list[str]:
    profile = ASR_FILE_PROFILES[key]
    selected = mode or profile.default_mode
    _validate_selection(key, profile, selected, language, audio)
    return [*_engine_arguments(profile, selected, audio, language), *_output_arguments(key, output)]


def environment(profile: FileAsrProfile, mode: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    folder = (profile.mode_executables or {}).get(mode or profile.default_mode, profile.executable).parent
    env["PATH"] = os.pathsep.join((str(folder), str(folder.parent / "lib"), env.get("PATH", "")))
    # Keep native auto-fetch caches inside canonical model storage, even for explicit future flags.
    env["NEMO_SPEECH_MODEL_DIR"] = str(project_cfg.component("asr/nemo-speechcpp").models_dir)
    env["SPEECH_MODEL_DIR"] = str(project_cfg.component("asr/speechcpp").models_dir)
    env.update(profile.environment_overrides)
    env.update((profile.mode_environments or {}).get(mode or profile.default_mode, ()))
    return env


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=tuple(ASR_FILE_PROFILES))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--mode", choices=("offline", "streaming", "live"))
    parser.add_argument("--language", default="auto")
    parser.add_argument("--output", type=Path, help="Transcript file for NeMo, AudioCpp or CrispASR")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--print-command", action="store_true")
    return parser


def _list_engines() -> None:
    for key, profile in ASR_FILE_PROFILES.items():
        missing = [str(path) for path in required_files(profile) if not path.is_file()]
        print(
            json.dumps(
                {
                    "engine": key,
                    "modes": list(profile.modes),
                    "missing": missing,
                    "streaming_kind": profile.streaming_kind,
                }
            )
        )


def _require_files(parser: argparse.ArgumentParser, command: list[str], profile: FileAsrProfile, args) -> None:
    for path in (Path(command[0]), *required_files(profile), *((args.input,) if args.input else ())):
        if not path.is_file():
            parser.error(f"Missing file: {path}")


def _prepare_output(parser: argparse.ArgumentParser, args) -> None:
    if not args.output:
        return
    if args.engine != "nemo-speechcpp" and not args.engine.startswith("audiocpp-"):
        parser.error("--output is not configured for this engine; redirect stdout instead")
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.list:
        _list_engines()
        return 0
    if not args.engine:
        parser.error("select --engine or --list")
    profile = ASR_FILE_PROFILES[args.engine]
    try:
        command = build_command(args.engine, args.input, args.mode, args.language, args.output)
    except ValueError as error:
        parser.error(str(error))
    if args.print_command:
        print(json.dumps(command))
        return 0
    require_native_execution(args.engine + " ASR")
    _require_files(parser, command, profile, args)
    _prepare_output(parser, args)
    print(f"ASR: {args.engine}; mode: {args.mode or profile.default_mode}", file=sys.stderr)
    return subprocess.run(
        command, env=environment(profile, args.mode), cwd=project_cfg.BASE_DIR, check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
