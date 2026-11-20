"""Voice source settings, workspace paths, loading and duration bookkeeping."""

import contextlib
import hashlib
import json
import math
import re
import subprocess
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from scripts.config import local_overlay
from scripts.launchers import launcher_config as cfg

DATA = Path(cfg.AUDIOCPP_INPUT_DIR)  # single source: launcher_config

PERSONAS = ["Default", "English", "ENG"]

DEFAULT_DUR_TARGET = 30

# - Audio files stream for minutes, so the bound is a stalled connection rather than total transfer time
DOWNLOAD_TIMEOUT = 60


@dataclass(frozen=True)
class DurationTarget:
    seconds: float
    mode: Literal["min", "max"]

    def __post_init__(self) -> None:
        if not math.isfinite(self.seconds) or self.seconds < 0:
            raise ValueError(f"Duration target must be a finite non-negative number: {self.seconds!r}")

    def as_json(self) -> list[float | str]:
        return [self.seconds, self.mode]


@dataclass(frozen=True, kw_only=True)
class CharacterConfig:
    category: str | None = None
    url: str | None
    exclude: frozenset[str] = frozenset()
    selected: tuple[str, ...] = ()
    count: int = 3
    selection: str | None = None
    fallback: str | None = None
    transcripts_xlsx: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError(f"Character config count must be positive: {self.count}")


@dataclass(frozen=True)
class CharacterWorkspace:
    root: Path
    name: str
    category: str | None = None

    def __post_init__(self) -> None:
        if not self.name or Path(self.name).name != self.name or self.name in (".", ".."):
            raise ValueError(f"Invalid character workspace name: {self.name!r}")
        if self.category is not None and (
            not self.category or Path(self.category).name != self.category or self.category in (".", "..")
        ):
            raise ValueError(f"Invalid character workspace category: {self.category!r}")

    @property
    def directory(self) -> Path:
        return self.root / self.category / self.name if self.category else self.root / self.name

    @property
    def generated(self) -> Path:
        """Everything this tool creates:
        - sources (the extracted zip tree) live outside it and are never modified
        """
        return self.directory / "generated"

    @property
    def selected(self) -> Path:
        return self.generated / "selected"

    @property
    def cache(self) -> Path:
        return self.generated / "subtitles.json"

    @property
    def durations(self) -> Path:
        return self.generated / "durations.json"

    @property
    def archive(self) -> Path:
        return self.generated / f"{self.name}.zip"

    @property
    def source_manifest(self) -> Path:
        return self.generated / "source.json"

    def wav_suffix(self, duration_target: DurationTarget | None, count: int) -> str:
        if count <= 0:
            raise ValueError(f"WAV count must be positive: {count}")
        if duration_target:
            target = duration_target.seconds
            label = str(int(target)) if float(target).is_integer() else str(target).replace(".", "p")
            return f"{duration_target.mode}{label}"
        return str(count)

    def wav_path(self, duration_target: DurationTarget | None, count: int) -> Path:
        return self.generated / f"{self.name}_{self.wav_suffix(duration_target, count)}.wav"

    def reference_path(self, duration_target: DurationTarget | None, count: int) -> Path:
        return self.generated / f"{self.name}_{self.wav_suffix(duration_target, count)}.txt"


@dataclass(frozen=True)
class SelectionRequest:
    files: list[Path]
    mapping: dict[str, str]
    preferred: str
    fallback: str | None
    count: int
    excluded: set[str]
    selected_ids: list[str]
    durations: dict[str, float]
    duration_target: DurationTarget | None = None


@dataclass(frozen=True)
class SelectionResult:
    files: list[Path]
    method: str


@dataclass
class PreparationResult:
    character: str
    status: str
    selected: int
    method: str
    transcribed: int
    missing: list[str]
    length: float | None


def load_character_configs() -> dict[str, CharacterConfig]:
    """Voice sources live outside the repo: they describe third-party recordings, not engine code."""
    manifest = local_overlay.voice_sources_path()
    if not manifest.is_file():
        return {}
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    configs: dict[str, CharacterConfig] = {}
    for name, entry in (payload.get("voices") or {}).items():
        configs[name] = CharacterConfig(
            category=entry.get("category", ""),
            url=entry.get("url", ""),
            exclude=frozenset(entry.get("exclude") or ()),
            selected=tuple(entry.get("selected") or ()),
            count=int(entry.get("count") or 0),
            selection=entry.get("selection"),
            fallback=entry.get("fallback"),
            transcripts_xlsx=entry.get("transcripts_xlsx"),
            superseded_by=entry.get("superseded_by") or None,
        )
    return configs


CHARACTER_CONFIGS: dict[str, CharacterConfig] = load_character_configs()


def load_json(path: Path, default=None):
    """Read one JSON file, or `default` when it is absent.

    `default` stays bare because the callers pass a dict for a cache and a list for the empty-transcript
    set, so a single annotation would widen the return type for every caller.
    """
    if default is None:
        default = {}
    try:
        # - utf-8-sig: an editor may save a transcript cache with a BOM
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def hash_data(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def archive_digest(path):
    """SHA256 of a fetched archive: the archives change in place, so the bytes are the build."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_build(url):
    """The upstream build marker a library came from; soundspriters stamps `updated` into the url."""
    values = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("updated")
    return values[0] if values else None


def record_source(config, workspace):
    """Write generated/source.json once per fetched archive: url, build marker and digest.
    - nothing pins the archive bytes upstream, so the recorded digest is what a re-download can move
    """
    if not config.url or not workspace.archive.is_file() or workspace.source_manifest.is_file():
        return False
    save_json(
        workspace.source_manifest,
        {
            "url": config.url,
            "build": archive_build(config.url),
            "sha256": archive_digest(workspace.archive),
            "bytes": workspace.archive.stat().st_size,
        },
    )
    return True


def audio_id(path):
    m = re.match(r"^(?:\[[^\]]+\])?([0-9A-Fa-f]+)(?:\.[0-9A-Fa-f]+)?(?:[-_].*)?$", path.stem)
    return (m[1] if m else path.stem).lower()


def roots(downloaded):
    found = [p for name in PERSONAS for p in downloaded.rglob(name) if p.is_dir()]
    return list(dict.fromkeys(found)) or [downloaded]


def get_files(roots):
    for ext in ("*.ogg", "*.wav"):
        files = [f for r in roots for f in r.rglob(ext)]
        if files:
            # "[old]" files are superseded versions of the same clip (same id, sometimes different text)
            return [f for f in files if not f.stem.lower().startswith("[old]")]
    raise ValueError("No .ogg or .wav files found")


def voice_files(roots_, excluded, generated):
    """The clips a voice may use: excluded ids and superseded takes never reach the pool."""
    return [f for f in get_files(roots_) if generated not in f.parents and audio_id(f).lower() not in excluded]


def duration(path):
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def load_durations(path):
    data = load_json(path)
    out = {}
    for k, v in data.items():
        with contextlib.suppress(TypeError, ValueError):
            out[k] = float(v)
    return out


def get_duration(f, durations):
    """Return f's duration in seconds:
    - computed via ffprobe once and cached in durations
    """
    key = audio_id(f)
    if key not in durations:
        durations[key] = duration(f)
    return durations[key]


def accumulate(
    candidates: Sequence[Path],
    durations: dict[str, float],
    dur_mode: Literal["min", "max"],
    target: float,
    start_total: float = 0.0,
) -> tuple[list[Path], float, bool]:
    """Walk candidates in order, summing duration until the min/max target is satisfied.
    - "min": keep adding until the running total is >= target (the clip that crosses the line is included)
    - "max": stop at the first clip that would push the total over the target (no skipping ahead
      to shorter clips, so order is preserved and the result may end below the target)
    Returns (picked, total, cut) where cut is True if max mode stopped because of overflow.
    """
    picked = []
    total = start_total
    for f in candidates:
        d = get_duration(f, durations)
        if dur_mode == "max" and total + d > target:
            return picked, total, True
        picked.append(f)
        total += d
        if dur_mode == "min" and total >= target:
            break
    return picked, total, False
