"""Independent PCM fixtures; deliberately do not use production audio encoders."""

import io
import base64
import struct
import wave


def pcm_wav(frames: int, rate: int = 16000, channels: int = 1, *, sample: int = 1, silence_frames: int = 0) -> bytes:
    if min(frames, silence_frames) < 0 or rate <= 0 or channels <= 0:
        raise ValueError("Invalid WAV fixture dimensions")
    data = struct.pack("<h", sample) * (frames * channels)
    data += b"\x00\x00" * (silence_frames * channels)
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(data)
    return output.getvalue()


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS3sAAAAASUVORK5CYII=")


def wav_fixture() -> bytes:
    return pcm_wav(1600, sample=2000, silence_frames=8000)
