"""Common audio uploads for ASR backends and either chat consumer."""

import base64
import json
import urllib.request
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from typing import Any


@dataclass(frozen=True)
class AudioRequest:
    audio: bytes
    language: str = "auto"
    prompt: str = ""
    suppress_non_speech: bool = False
    response_format: str = "json"


def parse(body: bytes, content_type: str, language: str = "auto") -> AudioRequest:
    if content_type.lower().startswith("multipart/form-data"):
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        fields = {
            str(part.get_param("name", header="content-disposition")): part.get_payload(decode=True)
            for part in message.iter_parts()
        }
        audio = fields.pop("file", b"")
        payload: dict[str, Any] = {
            key: value.decode("utf-8") for key, value in fields.items() if isinstance(value, bytes)
        }
        payload["suppress_non_speech"] = payload.get("suppress_non_speech", "false").lower() == "true"
    else:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Transcription request must be a JSON object")
        encoded = payload.get("audio_data")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("audio_data must contain base64 audio")
        if encoded.startswith("data:audio/"):
            encoded = encoded.split(",", 1)[-1]
        audio = base64.b64decode(encoded, validate=True)
    if not isinstance(audio, bytes) or not audio:
        raise ValueError("Audio is empty or missing")
    lang = payload.get("langcode", payload.get("language", language))
    prompt, suppress = payload.get("prompt", ""), payload.get("suppress_non_speech", False)
    if not isinstance(lang, str) or not isinstance(prompt, str) or not isinstance(suppress, bool):
        raise ValueError("language/prompt must be strings and suppress_non_speech must be a boolean")
    return AudioRequest(
        audio, lang.strip().lower() or language, prompt, suppress, payload.get("response_format", "json")
    )


def multipart_body(body: bytes, content_type: str, language: str = "auto") -> tuple[bytes, str]:
    if content_type.lower().startswith("multipart/form-data"):
        return body, content_type
    request = parse(body, content_type, language)
    fields = {
        "response_format": request.response_format,
        "language": request.language,
        "prompt": request.prompt,
        "suppress_non_speech": str(request.suppress_non_speech).lower(),
    }
    from scripts.launchers.shared.transport.multipart import audio_upload

    return audio_upload(request.audio, fields)


def post(url: str, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    forwarded = {
        key: value
        for key, value in (headers or {}).items()
        if key.lower() not in ("content-type", "content-length", "host", "connection")
    }
    forwarded["Content-Type"] = content_type
    request = urllib.request.Request(url, body, forwarded)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), response.headers.get("Content-Type", "application/json")
