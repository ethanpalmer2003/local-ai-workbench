"""Compare Kobold Lite text delivery modes using one completed Rocinante reply."""

import argparse
import base64
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.tests.shared.backends import backend_sessions
from scripts.tests.shared.paths import CasePaths

MODES = ("narration", "sentences", "whole")
NODE_SEGMENTER = """
const fs = require('node:fs');
const vm = require('node:vm');
let text = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => text += chunk);
process.stdin.on('end', () => {
  const mode = process.argv[1];
  const controls = Object.fromEntries(['enabled','buffer','rate','transport','text-mode','text-limit','tone-tags','tone-help',
    'policy','frames','lookahead','stop','close','status'].map(id => ['#kas-' + id, {
      id:'kas-' + id, value:'', checked:true, type:id === 'enabled' ? 'checkbox' : 'number'}]));
  const node = () => ({append() {}, setAttribute() {}, addEventListener() {},
    querySelector(id) { return controls[id]; }, querySelectorAll() { return Object.values(controls); }});
  const scope = vm.createContext({console, Intl, URL,
    document:{createElement:node, body:node(), querySelector:node},
    window:{koboldAudioSettings:{streaming_enabled:true, playback_buffer_ms:2000,
      pcm_sample_rate:24000, text_mode:mode, text_limit:400}},
    localStorage:{getItem() { return null; }}, closeTopNav() {}});
  vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), scope);
  process.stdout.write(JSON.stringify(scope.window.koboldAudioStream.chunkText(text)));
});
"""


def kobold_reply(timeout: float, max_tokens: int) -> dict[str, Any]:
    url = f"http://127.0.0.1:{cfg.KOBOLDCPP_KCPPS_ARGS['port']}/v1/chat/completions"
    payload = {
        "model": cfg.KOBOLDCPP_SERVICE.model,
        "messages": [
            {
                "role": "system",
                "content": "Write natural spoken replies in about five sentences. Use brief narration and dialogue; no list or heading.",
            },
            {"role": "user", "content": "Describe a quiet scouting mission near an enemy facility with a teammate."},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "seed": 4321,
        "stream": True,
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    first_token = None
    finish_reason = None
    tokens: list[str] = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            event = json.loads(data)
            choices = event.get("choices") or [{}]
            finish_reason = choices[0].get("finish_reason") or finish_reason
            delta = choices[0].get("delta", {})
            if token := delta.get("content"):
                if first_token is None:
                    first_token = time.perf_counter() - started
                tokens.append(str(token))
    text = "".join(tokens).strip()
    if not text:
        raise RuntimeError("Rocinante returned no generated text")
    return {
        "text": text,
        "elapsed_seconds": time.perf_counter() - started,
        "first_token_seconds": first_token,
        "stream_content_events": len(tokens),
        "finish_reason": finish_reason,
    }


def split_text(text: str, mode: str) -> list[str]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to match Kobold Lite's Intl.Segmenter sentence mode")
    result = subprocess.run(
        [node, "-e", NODE_SEGMENTER, mode, str(Path(cfg.__file__).parent / "koboldcpp/kobold_streaming.js")],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=10,
    )
    chunks = json.loads(result.stdout)
    if not chunks:
        raise RuntimeError(f"Kobold mode {mode!r} produced no speech chunks")
    return chunks


def speech_request(text: str, timeout: float) -> dict[str, Any]:
    url = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/v1/audio/speech"
    payload = {
        "input": text,
        "model": cfg.AUDIOCPP_SERVICE.model,
        "voice": cfg.AUDIOCPP_SERVICE.voice,
        "stream": True,
        "response_format": "pcm",
        "stream_format": "sse",
        "options": {"seed": "4321"},
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    first_data = None
    pcm = bytearray()
    audio_chunks: list[dict[str, float]] = []
    complete = False
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                complete = True
                break
            event = json.loads(data)
            if event.get("error") or event.get("type") == "error":
                raise RuntimeError(f"AudioCpp request failed: {event}")
            if event.get("type") == "speech.audio.delta":
                chunk = base64.b64decode(event["audio"])
                arrival = time.perf_counter() - started
                first_data = arrival if first_data is None else first_data
                duration = len(chunk) / 48000
                audio_chunks.append({"arrival": arrival, "duration": duration})
                pcm.extend(chunk)
    if not complete or not pcm:
        raise RuntimeError("AudioCpp returned incomplete or empty PCM")
    return {
        "pcm": bytes(pcm),
        "elapsed_seconds": time.perf_counter() - started,
        "first_data_seconds": first_data,
        "audio_seconds": len(pcm) / 48000,
        "chunks": audio_chunks,
    }


def simulated_underruns(chunks: list[dict[str, float]], buffer_seconds: float) -> int:
    playback_end = 0.0
    underruns = 0
    for index, chunk in enumerate(chunks):
        arrival = chunk["arrival"]
        if index == 0:
            playback_end = arrival + buffer_seconds + 0.02
        elif playback_end < arrival + 0.01:
            underruns += 1
            playback_end = arrival + buffer_seconds + 0.02
        playback_end += chunk["duration"]
    return underruns


def run(timeout: float, max_tokens: int, context: dict[str, Any]) -> Path:
    started = time.perf_counter()
    case = CasePaths(__file__)
    paths = case.new_run()
    with backend_sessions(paths, ("kobold", "audio")) as memory:
        memory.stage = "rocinante-generation"
        generated = kobold_reply(timeout, max_tokens)
        (paths.artifacts / "rocinante-reply.txt").write_text(generated["text"] + "\n", encoding="utf-8")
        warmup_text = split_text(generated["text"], "narration")[0]
        memory.stage = "breeze-warmup"
        warmup = speech_request(warmup_text, timeout)

        per_mode: dict[str, dict[str, Any]] = {}
        for mode in MODES:
            memory.stage = f"breeze-{mode}"
            chunks = split_text(generated["text"], mode)
            # The completed Rocinante response is reused; these requests never overlap LLM generation.
            pcm = bytearray()
            requests = []
            underruns = 0
            generation_start = time.perf_counter()
            for index, chunk in enumerate(chunks):
                measured = speech_request(chunk, timeout)
                pcm.extend(measured.pop("pcm"))
                underruns += simulated_underruns(measured["chunks"], 2.0)
                requests.append({"index": index, "text": chunk, **measured})
            mode_elapsed = time.perf_counter() - generation_start
            audio_seconds = len(pcm) / 48000
            wav_path = paths.artifacts / f"{mode}.wav"
            with wave.open(str(wav_path), "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                wav.writeframes(pcm)
            per_mode[mode] = {
                "chunk_count": len(chunks),
                "chunks": chunks,
                "requests": requests,
                "total_tts_seconds": mode_elapsed,
                "audio_seconds": audio_seconds,
                "rtf": mode_elapsed / audio_seconds if audio_seconds else None,
                "simulated_underruns_at_2s": underruns,
                "wav": wav_path.name,
            }
            print(
                json.dumps(
                    {"mode": mode, **{k: v for k, v in per_mode[mode].items() if k not in ("chunks", "requests")}}
                ),
                flush=True,
            )

    report = {
        "name": "Kobold Rocinante reply delivered to Breeze through AudioCpp proxy",
        "execution_context": context,
        "model": cfg.KOBOLDCPP_SERVICE.model,
        "audiocpp_model": cfg.AUDIOCPP_SERVICE.model,
        "voice": cfg.AUDIOCPP_SERVICE.voice,
        "playback_buffer_ms": 2000,
        "generation": {key: value for key, value in generated.items() if key != "text"},
        "warmup": {key: value for key, value in warmup.items() if key != "pcm" and key != "chunks"},
        "llm_generation_finished_before_tts": True,
        "delivery_modes": per_mode,
        "limits": [
            "One completed Rocinante reply is reused across the three modes; TTS does not run during LLM generation.",
            "Underruns are simulated per request at 2 seconds; browser playback and queue transition gaps are unmeasured.",
        ],
    }
    (paths.artifacts / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Sequential Rocinante to Breeze delivery modes",
        "",
        f"- Rocinante generation: {generated['elapsed_seconds']:.2f}s.",
        "- Same completed reply in each mode; generated-text warmup excluded.",
        "- Rocinante remained loaded; generation finished before TTS.",
        "",
        "| Kobold Lite mode | Requests | Audio (s) | TTS time (s) | RTF | Simulated underruns at 2 s |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, result in per_mode.items():
        lines.append(
            f"| {mode} | {result['chunk_count']} | {result['audio_seconds']:.2f} | "
            f"{result['total_tts_seconds']:.2f} | {result['rtf']:.2f} | {result['simulated_underruns_at_2s']} |"
        )
    lines.extend(["", "- Underruns: per-request simulation; browser playback and queue transition gaps unmeasured."])
    (paths.artifacts / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths.write_report(
        {
            "name": "Kobold to Breeze delivery modes",
            "category": "probes",
            "status": "completed",
            "total_seconds": time.perf_counter() - started,
            "reasoning": "Same generated reply tested through three proxy delivery modes; browser playback remains unverified.",
        }
    )
    return paths.artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-tokens", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    if cfg.AUDIOCPP_SERVICE.model != cfg.AudiocppModel.BREEZE_TTS.value:
        raise RuntimeError("Select Breeze 2 as the AudioCpp proxy model before running this probe")
    context = dict(require_native_execution("Kobold/Breeze comparison"))
    print(json.dumps({"execution_context": context}), flush=True)
    artifacts = run(args.timeout, args.max_tokens, context)
    print(artifacts)


if __name__ == "__main__":
    main()
