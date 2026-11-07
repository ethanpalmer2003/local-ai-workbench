"""Generate one complete Gemma reply, then compare Breeze delivery modes on the same text."""

import argparse
import json
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp import chat_models, language_practice
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.shared.services.process import stop_owned
from scripts.tests.cases.koboldcpp.kobold_audiocpp_modes import MODES, simulated_underruns, speech_request, split_text
from scripts.tests.shared.backends import backend_sessions
from scripts.tests.shared.paths import CasePaths


def gemma_reply(timeout: float, max_tokens: int) -> dict[str, Any]:
    url = f"http://127.0.0.1:{cfg.LLAMACPP_PRACTICE.internal_port}/v1/chat/completions"
    payload = {
        "model": "speech-workspace-chat",
        "messages": [
            {
                "role": "system",
                "content": "Write a natural spoken reply in about five sentences. Use brief narration and dialogue; no list or heading.",
            },
            {"role": "user", "content": "Describe a quiet scouting mission near an enemy facility with a teammate."},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "seed": 4321,
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    first_token = None
    finish_reason = None
    pieces: list[str] = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            if not data:
                continue
            event = json.loads(data)
            if event.get("error"):
                raise RuntimeError(event["error"].get("message", "Gemma generation failed"))
            choice = (event.get("choices") or [{}])[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta", {}).get("content")
            if delta:
                if first_token is None:
                    first_token = time.perf_counter() - started
                pieces.append(str(delta))
    text = "".join(pieces).strip()
    if not text:
        raise RuntimeError("Gemma returned no generated text")
    if finish_reason == "length":
        raise RuntimeError("Gemma reply reached max_tokens; rerun with a higher --max-tokens value")
    return {
        "text": text,
        "elapsed_seconds": time.perf_counter() - started,
        "first_token_seconds": first_token,
        "content_events": len(pieces),
        "finish_reason": finish_reason,
        "request": payload,
    }


def save_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)


def run(timeout: float, max_tokens: int) -> Path:
    if cfg.AUDIOCPP_SERVICE.model != cfg.AudiocppModel.BREEZE_TTS.value:
        raise RuntimeError("Select Breeze 2 as the AudioCpp proxy model before running this probe")

    context = require_native_execution("Gemma/Breeze sequential benchmark")
    paths = CasePaths(__file__).new_run()
    print(json.dumps({"execution_context": context, "output": str(paths.root)}), flush=True)
    started = time.perf_counter()
    gemma_process = None
    report: dict[str, Any] = {
        "name": "Gemma E4B generated reply delivered to Breeze 2 Q4_0",
        "status": "running",
        "execution_context": context,
        "llm_model": cfg.LANGUAGE_PRACTICE.llm_model,
        "llm_model_path": str(chat_models.path(cfg.LANGUAGE_PRACTICE.llm_model)),
        "tts_model": cfg.AUDIOCPP_SERVICE.model,
        "voice": cfg.AUDIOCPP_SERVICE.voice,
        "llm_generation_finished_before_tts": True,
    }
    try:
        with backend_sessions(paths, ("audio",)) as memory:
            memory.stage = "gemma_startup"
            gemma_process = language_practice.start_chat(cfg.LANGUAGE_PRACTICE.llm_model)
            port = cfg.LLAMACPP_PRACTICE.internal_port
            pids = launch_util.listening_process_ids(port)
            if not pids:
                raise RuntimeError(f"No Gemma listener found on port {port}")
            memory.watch_backend("gemma", pids)

            memory.stage = "gemma_generation"
            generation = gemma_reply(timeout, max_tokens)
            reply = generation.pop("text")
            (paths.artifacts / "gemma-reply.txt").write_text(reply + "\n", encoding="utf-8")

            memory.stage = "breeze_warmup"
            warmup_text = split_text(reply, "narration")[0]
            warmup = speech_request(warmup_text, min(timeout, 45))

            delivery_modes: dict[str, dict[str, Any]] = {}
            for mode in MODES:
                memory.stage = f"breeze_{mode}"
                chunks = split_text(reply, mode)
                pcm = bytearray()
                requests = []
                underruns = 0
                tts_started = time.perf_counter()
                for index, chunk in enumerate(chunks):
                    measured = speech_request(chunk, timeout)
                    pcm.extend(measured.pop("pcm"))
                    underruns += simulated_underruns(measured["chunks"], 2.0)
                    requests.append({"index": index, "text": chunk, **measured})
                tts_elapsed = time.perf_counter() - tts_started
                audio_seconds = len(pcm) / 48000
                wav_name = f"gemma-{mode}.wav"
                save_wav(paths.artifacts / wav_name, bytes(pcm))
                delivery_modes[mode] = {
                    "request_count": len(requests),
                    "requests": requests,
                    "tts_wall_seconds": tts_elapsed,
                    "summed_request_seconds": sum(row["elapsed_seconds"] for row in requests),
                    "first_audio_seconds": requests[0]["first_data_seconds"],
                    "audio_seconds": audio_seconds,
                    "rtf": tts_elapsed / audio_seconds,
                    "simulated_underruns_at_2s": underruns,
                    "generation_plus_tts_seconds": generation["elapsed_seconds"] + tts_elapsed,
                    "wav": wav_name,
                }
            memory.stage = "complete"

            report.update(
                status="completed",
                generation=generation,
                delivery_modes=delivery_modes,
                warmup_seconds=warmup["elapsed_seconds"],
                generated_text=reply,
                measurement="One completed Gemma reply reused in narration, separate-sentence and full-reply modes; no inference overlap.",
            )
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        if gemma_process is not None:
            stop_owned(gemma_process)
        report["total_seconds"] = time.perf_counter() - started
        (paths.artifacts / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if report["status"] == "completed":
            token = context["windows_token"]
            lines = [
                "# Gemma E4B delivery modes on Breeze 2 Q4_0",
                "",
                "Gemma completed one reply before TTS; that same text was reused in every mode.",
                "",
                f"Gemma generation: {report['generation']['elapsed_seconds']:.2f}s "
                f"(first token {report['generation']['first_token_seconds']:.2f}s).",
                "",
                "| Mode | Requests | First audio | TTS wall | Audio | RTF | LLM + TTS | Simulated underruns |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                *[
                    f"| {mode} | {row['request_count']} | {row['first_audio_seconds']:.2f}s | "
                    f"{row['tts_wall_seconds']:.2f}s | {row['audio_seconds']:.2f}s | {row['rtf']:.2f} | "
                    f"{row['generation_plus_tts_seconds']:.2f}s | {row['simulated_underruns_at_2s']} |"
                    for mode, row in report["delivery_modes"].items()
                ],
                "",
                f"Generated reply: {report['generated_text']}",
                "",
                f"Execution context: AppContainer={token['app_container'] if token else 'unknown'}, administrator elevated={token['administrator_elevated'] if token else 'unknown'}.",
            ]
            (paths.artifacts / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.write_report(
            {
                "name": report["name"],
                "category": "llamacpp",
                "status": report["status"],
                "total_seconds": report["total_seconds"],
                "reasoning": report.get("measurement", report.get("error", "Incomplete run")),
            }
        )
    return paths.artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-tokens", type=int, default=220)
    parser.add_argument("--timeout", type=float, default=75)
    args = parser.parse_args()
    print(run(args.timeout, args.max_tokens), flush=True)


if __name__ == "__main__":
    main()
