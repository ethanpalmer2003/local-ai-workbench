"""Shared paths and tuning values for the custom voice-recording workflow.

- Paths derive from the input overlay ([local_overlay.py](../../config/local_overlay.py)); no per-character constants live here
- Silence/tuning values are consumed by split_from_csv.py and tune_silence.py
"""

from dataclasses import dataclass
from pathlib import Path

from scripts.config import local_overlay

SILENCE_NOISE_DB = -35.0
SILENCE_MIN_DUR = 0.35
MAX_MERGED_DUR = 15.0
NOISE_DB_VALUES = [-35, -30, -25, -20, -16, -12]
MIN_DUR_VALUES = [0.15, 0.25, 0.35]

AUDIO_SUFFIXES = (".mp3", ".wav", ".ogg", ".flac", ".m4a")


@dataclass(frozen=True)
class SourcePaths:
    voice: str
    source_dir: Path
    csv_path: Path
    media_path: Path
    out_dir: Path
    subtitles_path: Path
    silence_cache_path: Path


def source_paths(voice: str) -> SourcePaths:
    """One recording workflow's paths under `<input>/audio/<voice>/source`."""
    source_dir = local_overlay.voice_dir(voice) / "source"
    media = sorted(path for path in source_dir.glob("*") if path.suffix.lower() in AUDIO_SUFFIXES)
    if not media:
        raise FileNotFoundError(f"No source recording for voice {voice!r} in {source_dir}")
    return SourcePaths(
        voice=voice,
        source_dir=source_dir,
        csv_path=source_dir / "full.csv",
        media_path=media[0],
        out_dir=source_dir,
        subtitles_path=source_dir / "subtitles.json",
        silence_cache_path=source_dir / "silence_cache.json",
    )
