"""Benchmark uploads use the production serializer; correctness fixtures stay independent."""

from scripts.launchers.shared.transport.multipart import audio_upload


def multipart(audio: bytes, *, language: str = "en", model: str | None = None) -> tuple[bytes, str]:
    fields = {"response_format": "json", "language": language}
    if model is not None:
        fields["model"] = model
    return audio_upload(audio, fields, filename="clip.wav")
