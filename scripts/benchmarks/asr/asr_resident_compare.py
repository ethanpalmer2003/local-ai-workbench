"""Resident ASR comparison using the domain-neutral benchmark lifecycle."""

import argparse
import base64
import functools
import hashlib
import importlib
import json
import time
import urllib.error
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.benchmark import summarize_requests
from scripts.benchmarks.shared.paths import BenchmarkPaths
from scripts.benchmarks.shared.resident_http import ResidentHttp
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.launchers.asr.shared.file_cli import environment
from scripts.launchers.asr.shared.resident_profiles import audio_config, clean_transcript, profiles
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.tests.cases.asr.shared.corpus import prepare_corpus
from scripts.tests.cases.asr.shared.metrics import unicode_errors
from scripts.tests.cases.asr.shared.requests import multipart
from scripts.tests.shared.resources import monitor_process


def _file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a model or projector file."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _clip_audio(clip: dict[str, Any]) -> bytes:
    """Read the saved audio bytes of one prepared corpus clip."""
    return Path(clip["file"]).read_bytes()


def _request_payloads(name: str, clips: list[dict[str, Any]]) -> tuple[str, list[tuple[bytes, str]]]:
    """Return the transcription endpoint and the per-clip payloads for one resident engine."""
    payloads: list[tuple[bytes, str]] = [
        multipart(
            _clip_audio(clip),
            language=clip.get("language", "en"),
            model="benchmark-asr" if name.startswith("audiocpp-") else None,
        )
        for clip in clips
    ]
    endpoint = "/inference" if name == "whispercpp-vulkan-fa" else "/v1/audio/transcriptions"
    if name == "koboldcpp-whisper":
        endpoint = "/api/extra/transcribe"
        payloads = [
            (
                json.dumps(
                    {"audio_data": base64.b64encode(_clip_audio(clip)).decode(), "langcode": clip.get("language", "en")}
                ).encode(),
                "application/json",
            )
            for clip in clips
        ]
    if name in ("llamacpp-gemma-audio", "llamacpp-granite-5-2b"):
        from scripts.launchers.asr.llamacpp import gemma_audio
        from scripts.launchers.asr.shared.requests import parse

        endpoint = "/v1/chat/completions"
        payloads = [(gemma_audio.chat_request(parse(body, kind)), "application/json") for body, kind in payloads]
        if name == "llamacpp-granite-5-2b":
            for index, (body, _) in enumerate(payloads):
                request = json.loads(body)
                request["messages"][0]["content"][0]["text"] = (
                    "Transcribe the speech with proper punctuation and capitalization."
                )
                payloads[index] = (json.dumps(request).encode(), "application/json")
    return endpoint, payloads


def _collect_samples(timer, infer, clips, repetitions, result) -> None:
    """Measure every clip for each repetition and append the rows to the run result."""
    for repetition in range(repetitions):
        for index, clip in enumerate(clips):
            text, timing = timer.measure(lambda: infer(index))
            result["samples"].append(
                {
                    **timing,
                    "clip": clip["id"],
                    "text": text,
                    "repetition": repetition,
                    "rtf": timing["request_seconds"] / clip["duration_seconds"],
                    **unicode_errors(clip["reference"], text),
                }
            )


def _infer(server, endpoint, payloads, index, deadline, name):
    """One timed request inside the whole-run budget."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Whole-run budget exhausted")
    server.timeout = min(60, remaining)
    body, content_type = payloads[index]
    try:
        value = server.post(endpoint, body, content_type)
    except urllib.error.HTTPError as error:
        detail = error.read(8192).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    if name in ("llamacpp-gemma-audio", "llamacpp-granite-5-2b"):
        choice = value["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("Gemma output truncated")
        value = {"text": choice["message"]["content"]}
    elif name == "llamacpp-qwen-1.7b":
        from scripts.launchers.asr.llamacpp.qwen3_asr import clean_transcript as clean_qwen_transcript

        value["text"] = clean_qwen_transcript(value.get("text", ""))
    if not isinstance(value.get("text"), str) or not value["text"].strip():
        raise ValueError("ASR returned no transcript")
    return clean_transcript(name, value["text"])


def _engine_command(name, command, run):
    if not name.startswith("audiocpp-"):
        return command
    config = run.temp / f"{name}.json"
    config.write_text(json.dumps(audio_config(name)), encoding="utf-8")
    return [part.replace("{config}", str(config)) for part in command]


def _run_engine(name, command, clips, samples, run, port, deadline, resources, result) -> None:
    command = _engine_command(name, command, run)
    result["command"] = command
    server = ResidentHttp(
        command,
        port,
        run.logs / f"{name}.log",
        model_identity=result["model_sha256"],
        env=environment(ASR_FILE_PROFILES[name]) if name in ASR_FILE_PROFILES else None,
        readiness="/api/extra/version" if name == "koboldcpp-whisper" else "/health",
    )
    try:
        with server.lifecycle as timer, ExitStack() as monitors:
            server.timeout = min(60, max(0.1, deadline - time.monotonic()))
            timer.prepare(server.start, combined=not name.startswith("audiocpp-"))
            phase = ["warmup"]
            if resources and server.process:
                result["resources"] = monitors.enter_context(
                    monitor_process(
                        server.process,
                        run.logs / f"{name}-vram.jsonl",
                        seconds=max(1, deadline - time.monotonic()),
                        phase=lambda: phase[0],
                    )
                )
            endpoint, payloads = _request_payloads(name, clips)
            infer = functools.partial(_infer, server, endpoint, payloads, deadline=deadline, name=name)
            timer.warmup(lambda: infer(0), includes_model_load=True)
            phase[0] = "resident_request"
            _collect_samples(timer, infer, clips, samples, result)
            result["status"] = "completed"
    except Exception as error:
        result.update(status="failed", error=str(error))
    result["benchmark"] = server.lifecycle.record()
    result["summary"] = summarize_requests(result["samples"])


def run_engine(name, command, model, clips, samples, run, port, deadline, resources=False):
    digest = _file_sha256(model)
    result: dict[str, Any] = {
        "engine": name,
        "command": command,
        "model": str(model),
        "model_sha256": digest,
        "status": "running",
        "samples": [],
    }
    if "--mmproj" in command:
        projector = Path(command[command.index("--mmproj") + 1])
        result["projector"] = {"file": str(projector), "sha256": _file_sha256(projector)}
    _run_engine(name, command, clips, samples, run, port, deadline, resources, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Opt in to native inference")
    parser.add_argument("--engines", nargs="+", help="Default: every configured resident adapter")
    parser.add_argument("--group", choices=["leaderboard-high-ranking"])
    parser.add_argument("--resources", action="store_true", help="Sample owned server CPU/RAM/GPU after readiness")
    parser.add_argument(
        "--language", help="Explicit corpus language for every engine; omit to retain manifest language"
    )
    parser.add_argument("--samples", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--clips", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--port", type=int, default=18941)
    parser.add_argument("--budget", type=int, choices=range(1, 241), default=180)
    return parser


def _selected_engines(parser, args, available) -> list[str]:
    if args.group:
        group = json.loads((project_cfg.CONFIG_DIR / "asr/leaderboard_group.json").read_text(encoding="utf-8"))
        args.engines = [member["engine"] for member in group["members"]]
    engines = args.engines or list(available)
    for name in engines:
        if name not in available:
            parser.error(f"No resident adapter for {name}; see coverage ledger")
    return engines


def _engine_result(name, command, model, clips, args, run, deadline) -> dict[str, Any]:
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("Whole-run budget exhausted; engine not omitted")
        if name == "sherpa-onnx":
            return importlib.import_module("scripts.tests.cases.asr.sherpa-onnx.resident").run_engine(
                clips, args.samples, deadline
            )
        return run_engine(name, command, model, clips, args.samples, run, args.port, deadline, args.resources)
    except Exception as error:
        return {"engine": name, "status": "failed", "error": str(error), "summary": summarize_requests([])}


def main():
    parser = _parser()
    args = parser.parse_args()
    available = profiles(args.port)
    engines = _selected_engines(parser, args, available)
    if not args.run:
        print(json.dumps({key: value[0] for key, value in available.items()}, indent=2))
        return 0
    context = dict(require_native_execution("Resident ASR benchmark"))
    run = BenchmarkPaths(__file__).new_run()
    clips = prepare_corpus(run, args.corpus)[: args.clips]
    if args.language:
        for clip in clips:
            clip["language"] = args.language
    report: dict[str, Any] = {
        "name": "Resident ASR comparison",
        "execution_context": context,
        "clips": clips,
        "results": [],
        "group": args.group,
        "language_override": args.language,
        "measurement_scope": "Isolated ASR; saved Kokoro clips; no parallel LLM/TTS inference. Resources sampled after readiness; startup memory not measured.",
    }
    from scripts.tests.cases.asr.shared.coverage import coverage

    report["coverage"] = coverage()
    deadline = time.monotonic() + args.budget
    for name in engines:
        command, model = available[name]
        result = _engine_result(name, command, model, clips, args, run, deadline)
        report["results"].append(result)
        (run.artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"engine": name, "status": result["status"], "summary": result["summary"], "error": result.get("error")}
            ),
            flush=True,
        )
    print(f"[OUTPUT] {run.root}")
    return int(any(row["status"] != "completed" for row in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
