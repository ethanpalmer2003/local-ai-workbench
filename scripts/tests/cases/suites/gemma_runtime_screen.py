"""Brief non-thinking Gemma E4B conversation screen; shared resident timing."""

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

from scripts.benchmarks.coding_agents.shared.benchmark_requests import observe_chunk
from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.resident_http import ResidentHttp
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.tests.shared.paths import CasePaths

PROMPTS = (
    "I am learning English. Ask me one short question about my day. Reply with just the question.",
    "Correct this sentence and give one short explanation: Yesterday I go to the shop. Use at most two sentences.",
)


def command(engine: str, port: int) -> list[str]:
    model = str(cfg.GEMMA_AUDIO_ASR.model)
    if engine == "koboldcpp":
        return [
            str(cfg.KOBOLDCPP_SERVICE.exe),
            "--model",
            model,
            "--usevulkan",
            "0",
            "--gpulayers",
            "999",
            "--contextsize",
            "8192",
            "--threads",
            "4",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--quantkv",
            "f16",
            "--reasoningeffort",
            "none",
            "--jinja",
            "--jinjathink",
            "false",
            "--quiet",
        ]
    return [
        str(cfg.GEMMA_AUDIO_ASR.exe),
        "-m",
        model,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--device",
        "Vulkan0",
        "-ngl",
        "999",
        "-fa",
        "on",
        "-c",
        "8192",
        "-np",
        "1",
        "-t",
        "4",
        "--jinja",
        "--reasoning-effort",
        "none",
        "--chat-template-kwargs",
        '{"enable_thinking":false}',
        "-ctk",
        "f16",
        "-ctv",
        "f16",
    ]


def generate(port: int, prompt: str, timing=None) -> dict[str, Any]:
    body = {
        "model": "gemma",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "seed": 42,
        "max_tokens": 192,
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    result: dict[str, Any] = {
        "prompt": prompt,
        "request": body,
        "text": "",
        "reasoning": "",
        "finished": False,
        "content_chunks": 0,
    }
    with urllib.request.urlopen(request, timeout=60) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            chunk = json.loads(data)
            observe_chunk(result, chunk, 0)
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                content = delta.get("content") or ""
                reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if timing and (content or reasoning):
                    timing.mark("first_output")
                if timing and content:
                    timing.mark("first_content")
                result["text"] += content
                result["content_chunks"] += bool(content)
                result["reasoning"] += reasoning
                if choice.get("finish_reason"):
                    result.update(finished=True, finish_reason=choice["finish_reason"])
    # Timings come exclusively from the shared request recorder, not observe_chunk's elapsed argument.
    result.pop("first_token_seconds", None)
    if not result["finished"] or not result["text"].strip():
        raise ValueError(f"No complete usable response: {result}")
    return result


def screen(engine, port, run, digest):
    cmd = command(engine, port)
    server = ResidentHttp(
        cmd,
        port,
        run.logs / f"{engine}.log",
        model_identity=digest,
        readiness="/api/extra/version" if engine == "koboldcpp" else "/health",
        timeout=60,
    )
    result: dict[str, Any] = {"engine": engine, "command": cmd, "model_sha256": digest, "samples": []}
    try:
        with server.lifecycle as timer:
            timer.prepare(server.start, combined=True)
            timer.warmup(lambda: generate(port, "Reply with exactly: Hello."))
            for prompt in PROMPTS:
                with timer.request() as timing:
                    row = generate(port, prompt, timing)
                row.update(timing.record())
                result["samples"].append(row)
                print(f"[{engine}] {row['request_seconds']:.3f}s {row['marks_seconds']} {row['text']!r}", flush=True)
        result["status"] = "completed"
    except Exception as error:
        result.update(status="failed", error=str(error))
    finally:
        result["benchmark"] = server.lifecycle.record()
        (run.artifacts / f"{engine}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    context = dict(require_native_execution("Brief Gemma runtime screen"))
    run = CasePaths(__file__).new_run()
    run.create()
    with cfg.GEMMA_AUDIO_ASR.model.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    results = []
    print(f"[OUTPUT] {run.root}", flush=True)
    for index, engine in enumerate(("koboldcpp", "llamacpp")):
        results.append(screen(engine, 18971 + index, run, digest))
    report = {
        "execution_context": context,
        "results": results,
        "provenance": provenance.block(
            subject="shared/gemma_runtime_screen",
            config={"execution_context": context},
            frameworks=[provenance.framework_state("koboldcpp"), provenance.framework_state("llamacpp")],
            models=[provenance.file_identity("chat", Path(cfg.GEMMA_AUDIO_ASR.model))],
        ),
        "limits": "One warmup/two short prompts; thinking disabled, 192-token cap; templates/cache/runtime defaults may differ. No ASR/TTS overlap or quality ranking.",
    }
    (run.artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return int(any(row["status"] != "completed" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
