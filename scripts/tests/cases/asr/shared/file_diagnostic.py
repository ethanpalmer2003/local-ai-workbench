"""Functional CLI transcript probe; no loading-inclusive speed leaderboard."""

import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.benchmark import measure_cold_process
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.launchers.asr.shared.file_cli import build_command, environment
from scripts.tests.cases.asr.shared.metrics import unicode_errors
from scripts.tests.shared.paths import RunPaths


def extract_text(engine: str, stdout: str, destination: Path) -> str:
    if destination.is_file():
        return destination.read_text(encoding="utf-8").strip()
    if engine in ("nemo-speechcpp", "crispasr") or engine.startswith("audiocpp-"):
        raise ValueError("Native CLI did not write the requested transcript file")
    if engine == "sherpa-onnx":
        texts: dict[int, str] = {}
        for line in stdout.splitlines():
            if not line.lstrip().startswith("{"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts[int(item.get("segment", 0))] = item["text"]
        if not texts:
            raise ValueError("No structured Sherpa transcript found; inspect the saved raw output")
        return " ".join(texts[key].strip() for key in sorted(texts)).strip()
    return stdout.strip()


def sample(engine: str, mode: str, clip: dict[str, Any], paths: RunPaths, timeout: float) -> dict[str, Any]:
    profile = ASR_FILE_PROFILES[engine]
    transcript_file = paths.artifacts / "transcript.txt"
    language = "auto" if engine == "funasr" else clip.get("language", "auto")
    command = build_command(engine, Path(clip["file"]), mode, language, transcript_file)
    try:
        native, timing = measure_cold_process(
            lambda: subprocess.run(
                command, env=environment(profile, mode), cwd=project_cfg.BASE_DIR, capture_output=True, timeout=timeout
            )
        )
    except subprocess.TimeoutExpired as error:
        (paths.logs / "stdout.log").write_bytes(error.stdout or b"")
        (paths.logs / "stderr.log").write_bytes(error.stderr or b"")
        raise
    (paths.logs / "stdout.log").write_bytes(native.stdout)
    (paths.logs / "stderr.log").write_bytes(native.stderr)
    if native.returncode:
        raise RuntimeError(f"CLI exit {native.returncode}; inspect {paths.logs}")
    transcript_stream = native.stdout.decode("utf-8", errors="replace")
    if engine == "sherpa-onnx":
        # The Windows streaming CLI writes recognition JSON alongside diagnostics on stderr.
        transcript_stream += "\n" + native.stderr.decode("utf-8", errors="replace")
    text = extract_text(engine, transcript_stream, transcript_file)
    if not text:
        raise ValueError("Empty transcript")
    return {
        "engine": engine,
        "mode": mode,
        "clip": clip["id"],
        "text": text,
        "command": command,
        **timing,
        "reference": clip["reference"],
        "language_selection": language,
        "streaming_kind": profile.streaming_kind,
        **unicode_errors(clip["reference"], text),
    }
