"""Binary-safe multipart encoding for upload adapters, independent of model/runtime."""

import uuid
from collections.abc import Mapping


def audio_upload(audio: bytes, fields: Mapping[str, str], *, filename: str = "speech.wav") -> tuple[bytes, str]:
    if any(char in filename for char in '\r\n"') or any(any(c in key for c in '\r\n"') for key in fields):
        raise ValueError("Invalid multipart filename or field name")
    boundary = "local-audio-" + uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        for key, value in fields.items()
    ]
    parts.extend(
        [
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'.encode(),
            audio,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
