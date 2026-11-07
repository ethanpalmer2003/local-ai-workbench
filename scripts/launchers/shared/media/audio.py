"""Audio decoding and PCM preparation shared by model adapters and test corpora."""

import io
import math
from pathlib import Path
from typing import Any


def decode_audio(source: bytes | Path) -> tuple[Any, int]:
    import soundfile as sf

    try:
        return sf.read(io.BytesIO(source) if isinstance(source, bytes) else source, always_2d=True, dtype="float32")
    except sf.LibsndfileError as error:
        raise ValueError("Cannot decode audio; send a valid WAV, FLAC or MP3 file") from error


def mono_resample(samples: Any, rate: int, target_rate: int = 16000, *, clip: bool = False) -> Any:
    import numpy as np
    from scipy.signal import resample_poly

    if rate <= 0 or target_rate <= 0:
        raise ValueError("Audio sample rates must be positive")
    if len(samples.shape) == 2:
        samples = np.mean(samples, axis=1)
    if rate != target_rate:
        divisor = math.gcd(rate, target_rate)
        samples = resample_poly(samples, target_rate // divisor, rate // divisor)
    return np.clip(samples, -1, 1) if clip else samples


def pcm_wav(samples: Any, rate: int = 16000) -> bytes:
    import soundfile as sf

    destination = io.BytesIO()
    sf.write(destination, samples, rate, format="WAV", subtype="PCM_16")
    return destination.getvalue()
