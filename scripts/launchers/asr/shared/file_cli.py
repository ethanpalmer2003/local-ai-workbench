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


def build_command(  # noqa: C901
    key: str, audio: Path | None, mode: str | None = None, language: str = "auto", output: Path | None = None
) -> list[str]:
    profile = ASR_FILE_PROFILES[key]
    selected = mode or profile.default_mode
    if selected not in profile.modes:
        raise ValueError(f"{key} supports these configured modes: {', '.join(profile.modes)}")
    if profile.languages and language.lower() not in profile.languages:
        raise ValueError(f"{key} accepts language selection: {', '.join(profile.languages)}")
    if selected != "live" and audio is None:
        raise ValueError("--input is required for file transcription")
    if selected == "live" and audio is not None:
        raise ValueError("--input and --mode live cannot be combined")
    arguments = [str((profile.mode_executables or {}).get(selected, profile.executable))]
    for value in profile.arguments:
        if selected == "live" and value == "{input}":
            continue
        arguments.append(value.format(input=str(audio) if audio else "", language=language))
    arguments += list(profile.modes[selected])
    if output is not None:
        if key == "nemo-speechcpp":
            arguments += ["--output", str(output)]
        elif key.startswith("audiocpp-"):
            arguments += ["--text-out", str(output)]
        elif key == "crispasr":
            arguments += ["--output-txt", "--output-file", str(output.with_suffix(""))]
    return arguments


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


def main() -> int:  # noqa: C901
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=tuple(ASR_FILE_PROFILES))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--mode", choices=("offline", "streaming", "live"))
    parser.add_argument("--language", default="auto")
    parser.add_argument("--output", type=Path, help="Transcript file for NeMo, AudioCpp or CrispASR")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    if args.list:
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
    for path in (Path(command[0]), *required_files(profile), *((args.input,) if args.input else ())):
        if not path.is_file():
            parser.error(f"Missing file: {path}")
    if args.output:
        if args.engine not in ("nemo-speechcpp", "crispasr") and not args.engine.startswith("audiocpp-"):
            parser.error("--output is not configured for this engine; redirect stdout instead")
        if args.output.exists():
            parser.error(f"Output already exists: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
    print(f"ASR: {args.engine}; mode: {args.mode or profile.default_mode}", file=sys.stderr)
    return subprocess.run(
        command, env=environment(profile, args.mode), cwd=project_cfg.BASE_DIR, check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
