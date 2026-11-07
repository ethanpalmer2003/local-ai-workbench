"""Bounded Gemma + selected standalone ASR + Lite integration smoke on temporary ports."""

import argparse
import base64
import contextlib
import json
import os
import subprocess
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.koboldcpp import kobold, kobold_lite
from scripts.launchers.asr.llamacpp import qwen3_asr as qwen_asr
from scripts.launchers.asr import selector as transcription
from scripts.launchers.asr.whispercpp import server as whisper
from scripts.tests.cases.asr.shared.requests import multipart
from scripts.tests.cases.asr.shared.corpus import prepare_corpus
from scripts.tests.cases.asr.shared.metrics import word_errors
from scripts.tests.shared.paths import CasePaths
from scripts.benchmarks.shared.reporting import report_run


def request(url: str, payload: bytes | None = None, content_type: str = "application/json") -> Any:
    with urllib.request.urlopen(
        urllib.request.Request(url, payload, {"Content-Type": content_type}), timeout=60
    ) as response:
        return json.load(response)


def main() -> None:
    import psutil

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcription-engine", choices=("whisper-vulkan", "qwen3-asr"), default="whisper-vulkan")
    args = parser.parse_args()
    context = dict(require_native_execution("Language-practice ASR integration"))
    if launch_util.llama_server_running():
        raise RuntimeError("Existing llama.cpp session retained; isolated integration check needs free runtimes")
    names = {
        "koboldcpp-nocuda.exe",
        "koboldcpp.exe",
        "whisper-server.exe",
        "llama-server.exe",
        "audiocpp_server.exe",
        "sd-server.exe",
    }
    active = [p.info for p in psutil.process_iter(["pid", "name"]) if (p.info["name"] or "").lower() in names]
    occupied = [port for port in (18885, 18886, 18887) if launch_util.port_listening(port)]
    if active or occupied:
        raise RuntimeError(f"Existing native sessions/occupied test ports; nothing was stopped: {active}, {occupied}")
    cfg.KOBOLDCPP_SERVICE.model = "llamacpp/gemma-4-E4B-it-Q4_0"
    cfg.KOBOLDCPP_SERVICE.transcription_engine = cfg.AsrStartupEngine(args.transcription_engine)
    cfg.KOBOLDCPP_SERVICE.streaming_ui_host, cfg.KOBOLDCPP_SERVICE.streaming_ui_port = "127.0.0.1", 18886
    cfg.KOBOLDCPP_KCPPS_ARGS.update(port=18885, port_param=18885)
    cfg.WHISPERCPP_ASR.port = 18887
    cfg.QWEN3_ASR.port = 18887
    run = CasePaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    commands = {
        "asr": transcription.backend(cfg.KOBOLDCPP_SERVICE.transcription_engine).command(),
        "kobold": kobold.server_command("shared"),
    }
    settings = {
        "execution_context": context,
        "commands": commands,
        "transcription_engine": args.transcription_engine,
        "asr_model": str(transcription.model(cfg.KOBOLDCPP_SERVICE.transcription_engine)),
    }
    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(cfg.LAUNCH.temp_dir), "TMP": str(cfg.LAUNCH.temp_dir)}
    processes: list[subprocess.Popen[Any]] = []
    servers: list[ThreadingHTTPServer] = []
    thread = None
    deadline = time.monotonic() + 180
    with report_run(run, "asr/shared/language_practice_whisper", "audio", settings=settings) as report:
        clips = prepare_corpus(run, None)
        with contextlib.ExitStack() as stack:
            try:
                for name, command in commands.items():
                    log = stack.enter_context((run.logs / f"{name}.log").open("wb"))
                    process = subprocess.Popen(
                        command, cwd=project_cfg.BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT
                    )
                    processes.append(process)
                    launch_util.assign_process_to_job(process.pid)
                    health = (
                        transcription.backend(cfg.KOBOLDCPP_SERVICE.transcription_engine).url() + "/health"
                        if name == "asr"
                        else "http://127.0.0.1:18885/api/extra/version"
                    )
                    while not launch_util.backend_ready(health):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError(f"{name} failed to start within the smoke budget; inspect {run.logs}")
                        time.sleep(0.2)
                thread = threading.Thread(
                    target=kobold_lite.run_proxy, kwargs={"on_server": servers.append}, daemon=True
                )
                thread.start()
                lite = "http://127.0.0.1:18886"
                while not launch_util.backend_ready(lite + "/health"):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Lite proxy startup exceeded smoke budget")
                    time.sleep(0.1)
                native_caps = request("http://127.0.0.1:18885/api/extra/version")
                proxy_caps = request(lite + "/api/extra/version")
                assert native_caps["transcribe"] is False and proxy_caps["transcribe"] is True
                with urllib.request.urlopen(lite, timeout=30) as response:
                    html = response.read().decode()
                assert "kobold_streaming.js" in html
                transcripts = []
                for index, clip in enumerate(clips[:2]):
                    audio = Path(clip["file"]).read_bytes()
                    if index == 0:
                        body = json.dumps({"audio_data": base64.b64encode(audio).decode(), "langcode": "en"}).encode()
                        path, content_type = "/api/extra/transcribe", "application/json"
                    else:
                        body, content_type = multipart(audio)
                        path = "/v1/audio/transcriptions"
                    result = request(lite + path, body, content_type)
                    accuracy = word_errors(clip["reference"], result["text"])
                    assert result["text"].strip() and accuracy["wer"] < 0.1
                    transcripts.append({"path": path, "text": result["text"], **accuracy})
                    print(f"[OK] {path}: {result['text']}", flush=True)
                reply = request(
                    lite + "/v1/chat/completions",
                    json.dumps(
                        {
                            "model": "gemma",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "Practise English with me. Give one short friendly reply to: "
                                    + transcripts[0]["text"],
                                }
                            ],
                            "max_tokens": 48,
                            "temperature": 0,
                        }
                    ).encode(),
                )
                assert reply["choices"][0]["message"]["content"].strip()
                assert (
                    qwen_asr.matching_server()
                    if args.transcription_engine == "qwen3-asr"
                    else whisper.matching_server()
                )
                report.results.append(
                    {
                        "status": "completed",
                        "native_capabilities": native_caps,
                        "proxy_capabilities": proxy_caps,
                        "transcripts": transcripts,
                        "reply": reply,
                    }
                )
            finally:
                for server in servers:
                    server.shutdown()
                if thread:
                    thread.join(timeout=5)
                for process in reversed(processes):
                    if process.poll() is None:
                        launch_util.kill_process_tree(process.pid)
                    process.wait(timeout=15)
        report.results.append(
            {"cleanup_ports_clear": all(not launch_util.port_listening(port) for port in (18885, 18886, 18887))}
        )
    print(f"[OK] {args.transcription_engine} -> Lite -> Gemma; task-owned services stopped", flush=True)


if __name__ == "__main__":
    main()
