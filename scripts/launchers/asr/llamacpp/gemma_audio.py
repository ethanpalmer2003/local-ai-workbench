"""Gemma 4 E4B audio ASR via OpenAI-style audio chat requests."""

import base64
import json
import subprocess
from typing import Any

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.shared import requests
from scripts.launchers.shared.services import native


def url() -> str:
    return f"http://127.0.0.1:{cfg.GEMMA_AUDIO_ASR.port}"


def ready() -> bool:
    return launch_util.backend_ready(url() + "/health")


def command() -> list[str]:
    settings = cfg.GEMMA_AUDIO_ASR
    return [
        str(settings.exe),
        "-m",
        str(settings.model),
        "--mmproj",
        str(settings.mmproj),
        "--host",
        "127.0.0.1",
        "--port",
        str(settings.port),
        "--alias",
        "gemma-audio",
        "--device",
        "Vulkan0",
        "-ngl",
        "999",
        "-fa",
        "on",
        "-c",
        str(settings.context_size),
        "-np",
        "1",
        "-t",
        str(settings.threads),
        "-n",
        str(settings.max_tokens),
        "--jinja",
    ]


def matching_server() -> bool:
    return native.matches(command())


def start() -> subprocess.Popen[Any] | None:
    if launch_util.llama_server_running():
        print("Existing llama.cpp chat session retained; Gemma audio uses its configured port")
    settings = cfg.GEMMA_AUDIO_ASR
    return native.start_server(
        command(),
        (settings.exe, settings.model, settings.mmproj),
        settings.port,
        "Gemma audio",
        ready,
        matching_server,
        component_key="asr/llamacpp",
    )


def prepare_audio(audio: bytes) -> tuple[str, float]:
    from scripts.launchers.shared.media.audio import decode_audio, mono_resample, pcm_wav

    samples, rate = decode_audio(audio)
    duration = len(samples) / rate
    if not 0 < duration <= cfg.GEMMA_AUDIO_ASR.max_audio_seconds:
        raise ValueError(
            f"Gemma audio accepts up to {cfg.GEMMA_AUDIO_ASR.max_audio_seconds:g} seconds; got {duration:.2f}s. Split the clip into shorter turns."
        )
    samples = mono_resample(samples, rate, clip=True)
    return base64.b64encode(pcm_wav(samples)).decode(), duration


def chat_request(request: requests.AudioRequest) -> bytes:
    if request.suppress_non_speech:
        raise ValueError("Non-speech token suppression is a Whisper-specific option")
    if request.response_format not in ("json", "text"):
        raise ValueError("Gemma audio supports response_format=json or text; it does not generate timestamps")
    audio, _ = prepare_audio(request.audio)
    language = {"en": "English", "es": "Spanish", "fr": "French"}.get(request.language, request.language)
    target = "the original spoken language" if language == "auto" else language
    prompt = f"Transcribe the following speech segment in {target} into {target} text.\nOnly output the transcription, with no commentary, translation, labels or newlines. Write numbers as digits."
    if request.prompt:
        prompt += "\nVocabulary context (not text to copy): " + request.prompt
    return json.dumps(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": cfg.GEMMA_AUDIO_ASR.max_tokens,
            "stream": False,
        }
    ).encode()


def transcribe(
    body: bytes, content_type: str, headers: dict[str, str] | None = None, server_url: str | None = None
) -> tuple[bytes, str]:
    request = requests.parse(body, content_type)
    payload = chat_request(request)
    data, _ = requests.post((server_url or url()) + "/v1/chat/completions", payload, "application/json", headers)
    response = json.loads(data)
    try:
        choice = response["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("Gemma returned an invalid chat-completion response") from error
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Gemma returned no transcription text")
    if choice.get("finish_reason") == "length":
        raise RuntimeError("Gemma transcription reached its output limit; shorten the recording")
    text = text.strip()
    return (
        (text.encode(), "text/plain; charset=utf-8")
        if request.response_format == "text"
        else (json.dumps({"text": text}).encode(), "application/json")
    )
