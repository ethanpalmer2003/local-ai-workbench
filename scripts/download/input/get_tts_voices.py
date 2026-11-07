import argparse
import contextlib
import hashlib
import json
import math
import random
import re
import shutil
import subprocess
import traceback
import urllib.request
import zipfile
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Any, Literal

from scripts.config import overlay_inputs as inputs
from scripts.file_util import archive_path
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.llamacpp import qwen3_asr
from scripts.launchers.shared.services.process import stop_owned
from scripts.launchers.shared.transport.multipart import audio_upload

DATA = Path(cfg.AUDIOCPP_INPUT_DIR)  # single source: launcher_config

PERSONAS = ["Default", "English", "ENG"]

DEFAULT_DUR_TARGET = 30


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
    ids: list[str]
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
    manifest = inputs.voice_sources_path()
    if not manifest.is_file():
        return {}
    payload = json.loads(manifest.read_text(encoding="utf-8"))
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
        )
    return configs


CHARACTER_CONFIGS: dict[str, CharacterConfig] = load_character_configs()


def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def hash_data(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def audio_id(path):
    m = re.match(r"^(?:\[[^\]]+\])?([0-9A-Fa-f]+)(?:\.[0-9A-Fa-f]+)?(?:[-_].*)?$", path.stem)
    return (m[1] if m else path.stem).lower()


def roots(downloaded):
    found = [p for name in PERSONAS for p in downloaded.rglob(name) if p.is_dir()]
    return list(dict.fromkeys(found)) or [downloaded]


def get_files(roots, excluded):
    for ext in ("*.ogg", "*.wav"):
        files = [f for r in roots for f in r.rglob(ext)]
        if files:
            # "[old]" files are superseded versions of the same clip (same id, sometimes different text)
            return [f for f in files if audio_id(f).lower() not in excluded and not f.stem.lower().startswith("[old]")]
    raise ValueError("No .ogg or .wav files found")


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


def accumulate(candidates, durations, dur_mode, target, start_total=0.0):
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


def norm_key(k):
    """Normalise an audio id/filename stem: strips '[tag]' prefix and '.0b2' style suffixes."""
    k = str(k).strip()
    m = re.match(r"^(?:\[[^\]]+\])?([0-9A-Fa-f]+)(?:\.[0-9A-Fa-f]+)?(?:[-_].*)?$", k)
    return (m[1] if m else k).lower()


_TYPO = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "})
_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def int_to_words(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        return f"{_ONES[n // 100]} hundred" + (f" {int_to_words(n % 100)}" if n % 100 else "")
    for size, name in ((10**6, "million"), (1000, "thousand")):
        if n >= size:
            head = f"{int_to_words(n // size)} {name}"
            return head + (f" {int_to_words(n % size)}" if n % size else "")
    return str(n)


def spell_numbers(s):
    """Spell plain integers (not 3.5, 1,000, 2B, 1st) so the text matches what is spoken."""
    return re.sub(r"(?<![\w.,])\d{1,9}(?!\w|[.,]\d)", lambda m: int_to_words(int(m[0])), s)


def clean_text(s):
    """Normalise a transcript for voice cloning: no filename underscores, plain punctuation,
    no symbols/emoji/tags, collapsed repeats, digits spelled out. Stage directions like
    '(sniffs)' are kept here and handled by is_speech() instead."""
    s = str(s).replace("_", "").translate(_TYPO).replace("\u2026", "...")
    s = re.sub(r"<[^>]*>", " ", s)
    s = re.sub(r"[*~#^|\\\U0001F300-\U0001FAFF\u2600-\u27BF]", " ", s)
    s = re.sub(r"[!?]{2,}", lambda m: "?" if "?" in m[0] else "!", s)
    s = re.sub(r"\.{4,}", "...", s)
    s = spell_numbers(s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


MIN_WORDS = 3
MAX_FILLER_RATIO = 0.4
_STAGE_DIRECTION = re.compile(r"[(\[][^)\]]*[)\]]")
_FILLER = re.compile(
    r"^(?:h+m+|m+|u+h+m*|u+m+|a+h+|o+h+|e+r+m*|g+a+h+|h+a+h+|h+u+h+|u+g+h+|c+o+u+g+h+|s+i+g+h+|g+r+o+a+n+|g+r+u+n+t+|h+e+h+e+|s)$",
    re.IGNORECASE,
)


def is_speech(text):
    """True if a transcript looks like real speech worth cloning from.
    Rejects stage directions ('(sniffs)'), clips under MIN_WORDS words, and mostly-filler clips
    (coughs, 'hmm', grunts)."""
    t = str(text).strip()
    if not t or _STAGE_DIRECTION.search(t):
        return False
    words = re.findall(r"[A-Za-z0-9']+", t)
    if len(words) < MIN_WORDS:
        return False
    return sum(bool(_FILLER.match(w)) for w in words) / len(words) <= MAX_FILLER_RATIO


def get_text(files):
    text = {}
    for f in files:
        m = re.match(r"^(.+?)-(.+)$", f.stem)
        if m and m[2].strip() and not re.match(r"^\s*\(", m[2]):
            cleaned = clean_text(m[2])
            if cleaned:
                text[norm_key(m[1])] = cleaned
    return text


def sort_map(mapping, durations, excluded):
    return dict(
        sorted(
            mapping.items(),
            key=lambda x: (
                2 if x[0] in excluded else 0 if x[1].strip() else 1,
                -len(x[1]) if x[1].strip() else -durations.get(x[0], 0),
            ),
        )
    )


def load_map(cache, files, durations, excluded):
    raw = load_json(cache)
    existing = {}

    for k, v in raw.items():
        key = norm_key(k)
        value = clean_text(v)
        if value or not existing.get(key, "").strip():
            existing[key] = value

    for k, v in get_text(files).items():
        if not existing.get(k, "").strip():
            existing[k] = v

    ids = {audio_id(f) for f in files}

    renamed = sum(norm_key(k) != str(k).lower() for k in raw)
    if renamed:
        print(f"NOTE: normalized {renamed} transcript keys (e.g. stripped '.0b2' suffixes).")

    # transcripts whose key matches no audio file: stale, or a key-format mismatch
    orphans = [k for k, v in existing.items() if v.strip() and k not in ids and k not in excluded]
    if orphans:
        print(
            f"WARNING: {len(orphans)} transcripts match no audio file (key mismatch?), e.g.: {', '.join(orphans[:5])}"
        )
        print(f"  sample file ids: {', '.join(sorted(ids)[:5])}")

    for f in files:
        existing.setdefault(audio_id(f), "")

    mapping = sort_map(existing, durations, excluded)
    missing = sum(not v.strip() for k, v in mapping.items() if k not in excluded)

    if missing:
        print(f"WARNING: {missing} IDs have no transcript.")
        print(f"Add transcripts to: {cache}")

    save_json(cache, mapping)
    return mapping


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "audiocpp-preparer"})
    with urllib.request.urlopen(req) as r, path.open("wb") as f:
        shutil.copyfileobj(r, f)


def ordered_pool(files, mapping, mode, ids, durations):
    if mode == "selected":
        by_id = {audio_id(f): f for f in files}
        out = []
        for x in ids:
            f = by_id.get(x.lower())
            if f is None:
                raise FileNotFoundError(f"Missing audio file: {x}")
            out.append(f)
        return out

    if mode == "random":
        pool = files[:]
        random.shuffle(pool)
        return pool

    by_id = {audio_id(f): f for f in files}

    if mode == "longestText":
        usable = {audio_id(f) for f in files if is_speech(mapping.get(audio_id(f), ""))}
        return [by_id[k] for k in mapping if k in usable]

    if mode == "longestAudio":
        usable = {audio_id(f) for f in files if not mapping.get(audio_id(f), "").strip()}
        return [by_id[k] for k in mapping if k in usable]

    if mode == "alphabeticalText":
        usable = [f for f in files if is_speech(mapping.get(audio_id(f), ""))]
        return sorted(usable, key=lambda f: f.name)

    if mode == "alphabeticalAudio":
        usable = [f for f in files if not mapping.get(audio_id(f), "").strip()]
        return sorted(usable, key=lambda f: f.name)

    raise ValueError(f"Invalid selection mode: {mode}")


def choose(files, mapping, mode, count, ids, durations):
    pool = ordered_pool(files, mapping, mode, ids, durations)
    return pool if mode == "selected" else pool[:count]


class VoiceSelector:
    # - longestText is the primary mode: orders by transcript length, so it needs transcripts to exist
    # - longestAudio is the bootstrap mode: picks UNTRANSCRIBED clips longest-first, purely so
    #   --transcribe can fill them in - once transcripts exist, selection goes back to longestText
    MODES = frozenset(("random", "longestAudio", "longestText", "selected", "alphabeticalText", "alphabeticalAudio"))

    def __init__(self, request: SelectionRequest):
        self.request = request
        if request.count < 0:
            raise ValueError("Selection count must not be negative")
        overlap = set(request.selected_ids) & request.excluded
        if overlap:
            raise ValueError(f"Required ID is excluded: {sorted(overlap)[0]}")

    def select(self):
        request = self.request
        by_id = {audio_id(f): f for f in request.files}
        required = []
        for x in request.selected_ids:
            if x not in by_id:
                raise FileNotFoundError(f"Required ID not found: {x}")
            required.append(by_id[x])

        used = {audio_id(f) for f in required}
        candidates = [f for f in request.files if audio_id(f) not in used]

        if request.duration_target:
            target = request.duration_target.seconds
            dur_mode = request.duration_target.mode
            total = sum(get_duration(f, request.durations) for f in required)
            if dur_mode == "max" and total > target:
                raise ValueError(f"Required clips alone exceed max duration: {total:.1f}s > {target}s")

            picked, total, cut = accumulate(
                ordered_pool(candidates, request.mapping, request.preferred, request.ids, request.durations),
                request.durations,
                dur_mode,
                target,
                total,
            )
            method = request.preferred

            if total < target and request.fallback and not cut:
                print(
                    f"Preferred '{request.preferred}' reached {total:.1f}s of {target}s ({dur_mode}); using '{request.fallback}' for the rest."
                )
                used.update(audio_id(f) for f in picked)
                remaining = [f for f in candidates if audio_id(f) not in used]
                more, total, _ = accumulate(
                    ordered_pool(remaining, request.mapping, request.fallback, request.ids, request.durations),
                    request.durations,
                    dur_mode,
                    target,
                    total,
                )
                if more:
                    picked += more
                    method = f"{request.preferred}+{request.fallback}"

            if dur_mode == "min" and total < target:
                raise ValueError(f"Not enough audio to reach minimum duration: {total:.1f}s < {target}s")
            return required + picked, method

        remaining = request.count - len(required)
        if remaining <= 0:
            return required[: request.count], "selected"

        selected = choose(candidates, request.mapping, request.preferred, remaining, request.ids, request.durations)
        method = request.preferred
        if len(selected) < remaining and request.fallback:
            needed = remaining - len(selected)
            print(
                f"Preferred '{request.preferred}' returned {len(selected)}/{remaining}; using '{request.fallback}' for {needed} more."
            )
            used.update(audio_id(f) for f in selected)
            candidates = [f for f in candidates if audio_id(f) not in used]
            selected += choose(candidates, request.mapping, request.fallback, needed, request.ids, request.durations)
            method = f"{request.preferred}+{request.fallback}"
        return required + selected, method


def select(request: SelectionRequest):
    return VoiceSelector(request).select()


def _selection_manifest_matches(manifest, current, selected_dir, keys):
    old = load_json(manifest)
    if not old or not all(old.get(k) == current[k] for k in keys):
        return None
    if not all((selected_dir / f["name"]).is_file() for f in old.get("files", [])):
        return None
    return old


def _materialize_selection(selected_dir, manifest, desired, current):
    current["files"] = [{"id": audio_id(f), "name": f.name} for f in desired]
    archive_path(selected_dir, selected_dir.parent)
    selected_dir.mkdir()
    for f in desired:
        shutil.copy2(f, selected_dir / f.name)
    save_json(manifest, current)


def get_selection(selected_dir: Path, request: SelectionRequest):
    manifest = selected_dir / "selection.json"
    inventory = sorted((audio_id(f), f.name) for f in request.files)

    current = {
        "selection": request.preferred,
        "fallback": request.fallback,
        "method": None,
        "count": request.count,
        "ids": request.ids,
        "duration_target": request.duration_target.as_json() if request.duration_target else None,
        "constraints": {"selected": request.selected_ids, "excluded": sorted(request.excluded)},
        "mapping": hash_data(request.mapping),
        "inventory": hash_data(inventory),
    }

    keys = ("selection", "fallback", "count", "ids", "duration_target", "constraints", "mapping", "inventory")

    old = _selection_manifest_matches(manifest, current, selected_dir, keys)
    if old is not None:
        print(f"Selected files match current preferences; reusing '{old['method']}'.")
        return SelectionResult([selected_dir / f["name"] for f in old["files"]], old["method"])

    desired, method = select(request)

    current["method"] = method
    _materialize_selection(selected_dir, manifest, desired, current)
    return SelectionResult([selected_dir / f.name for f in desired], method)


def transcribe_file(f, mapping, tmp):
    key = audio_id(f)
    audio = tmp / f"{key}.wav"
    txt = tmp / f"{key}.txt"

    print(f"Transcribing: {f.name}")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(f), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(audio)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    body, content_type = audio_upload(audio.read_bytes(), {"response_format": "json", "language": "auto"})
    result, response_type = qwen3_asr.transcribe(body, content_type)
    if "application/json" in response_type:
        payload = json.loads(result)
        transcript = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(transcript, str):
            raise RuntimeError(f"Qwen ASR returned no transcript for {f.name}")
    elif response_type.startswith("text/plain"):
        transcript = result.decode("utf-8", errors="replace")
    else:
        raise RuntimeError(f"Qwen ASR returned unsupported content type {response_type!r} for {f.name}")

    txt.write_text(transcript, encoding="utf-8")
    text = clean_text(transcript)
    if text:
        mapping[key] = text
        print(f"  {text}")
    else:
        print(f"  WARNING: empty transcription for {key}")


def transcribe(files, mapping, cache, durations, excluded):
    tmp = cache.parent / "stt_tmp"
    archive_path(tmp, cache.parent)
    tmp.mkdir()
    server_process = None
    server_ready = False

    try:
        for f in files:
            key = audio_id(f)
            if mapping.get(key, "").strip():
                print(f"Skipping existing transcript: {f.name}")
                continue
            if not server_ready:
                server_process = qwen3_asr.start()
                server_ready = True
            transcribe_file(f, mapping, tmp)
    finally:
        try:
            if server_process is not None:
                stop_owned(server_process)
        finally:
            archive_path(tmp, cache.parent)

    mapping = sort_map(mapping, durations, excluded)
    save_json(cache, mapping)
    return mapping


def build_wav(files, mapping, workspace, count, duration_target=None):
    if not files:
        raise ValueError("No files selected. Candidates may exceed the max duration budget.")

    wav = workspace.wav_path(duration_target, count)
    reference = workspace.reference_path(duration_target, count)

    reference.write_text(" ".join(mapping[audio_id(f)] for f in files), encoding="utf-8")

    inputs = [x for f in files for x in ("-i", str(f))]
    filt = "".join(f"[{i}:a]" for i in range(len(files)))
    filt += f"concat=n={len(files)}:v=0:a=1[out]"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filt,
            "-map",
            "[out]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        check=True,
    )

    length = duration(wav)

    print(f"Selected: {len(files)}")
    print(f"WAV: {wav}")
    print(f"Reference: {reference}")
    print(f"Length: {length:.1f}s")

    return wav, length


def ensure_sources(config: CharacterConfig, workspace: CharacterWorkspace) -> Path:
    """Sources = the character directory as-is (never reorganized).
    - if there's no source audio yet and a url is configured, fetch the zip and extract it
      into a subfolder named after the zip - same as a manual extract
    """
    directory = workspace.directory
    generated = workspace.generated
    for f in directory.rglob("*"):
        if f.is_file() and generated not in f.parents and f.suffix.lower() in (".ogg", ".wav", ".mp3"):
            print("DOWNLOAD MODE OFF (sources already present)")
            return directory

    if not config.url:
        raise FileNotFoundError(
            f"No source audio under {directory} and no url configured to fetch one - populate it manually."
        )
    print("DOWNLOAD MODE ON")
    generated.mkdir(parents=True, exist_ok=True)
    download(config.url, workspace.archive)
    target = directory / workspace.archive.stem
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(workspace.archive) as z:
        z.extractall(target)
    return directory


def import_xlsx_transcripts(xlsx_path: Path, files: list[Path], mapping: dict[str, str]) -> int:
    """Merge filename->transcript rows from an xlsx into the mapping cache.
    - rows are matched by audio filename stem
    - lazy-imports openpyxl
    """
    try:
        import openpyxl
    except ImportError:
        print(
            f"WARNING: openpyxl is not installed, skipping xlsx transcripts ({xlsx_path}). Install with: uv add openpyxl"
        )
        return 0

    ids = {audio_id(f) for f in files}
    added = 0
    workbook = openpyxl.load_workbook(xlsx_path, read_only=True)
    try:
        for row in chain.from_iterable(sheet.iter_rows(values_only=True) for sheet in workbook.worksheets):
            values = [str(cell).strip() for cell in row if cell is not None]
            for i, value in enumerate(values):
                key = value.lower()
                if key not in ids or i + 1 >= len(values):
                    continue
                text = values[i + 1]
                if not text or text.lower() in ids or mapping.get(key, "").strip():
                    continue
                mapping[key] = clean_text(text)
                added += 1
                break
    finally:
        workbook.close()
    return added


def transcribe_selected(selected_files, mapping, cache, durations, excluded, selected_dir, method):
    before = sum(bool(mapping.get(audio_id(f), "").strip()) for f in selected_files)
    mapping = transcribe(selected_files, mapping, cache, durations, excluded)
    transcribed = sum(bool(mapping.get(audio_id(f), "").strip()) for f in selected_files) - before
    save_json(cache.parent / "durations.json", durations)

    manifest = selected_dir / "selection.json"
    if manifest.exists():
        data = load_json(manifest)
        data["mapping"] = hash_data(mapping)
        data["method"] = method
        save_json(manifest, data)
    return mapping, transcribed


@dataclass
class VoiceInventory:
    files: list[Path]
    mapping: dict[str, str]
    durations: dict[str, float]


def prepare_sources(
    workspace: CharacterWorkspace, config: CharacterConfig, preferred: str, fallback: str | None
) -> VoiceInventory:
    directory = workspace.directory
    cache = workspace.cache
    durations_path = workspace.durations
    directory.mkdir(parents=True, exist_ok=True)
    workspace.generated.mkdir(parents=True, exist_ok=True)

    sources = ensure_sources(config, workspace)
    roots_ = roots(sources)
    print("Using folders:", ", ".join(p.name for p in roots_))

    excluded = set(config.exclude)
    files = [f for f in get_files(roots_, excluded) if workspace.generated not in f.parents]
    durations = load_durations(durations_path)

    # - only longestAudio actually ranks by duration; precompute durations just for it
    #   (longestText ranks by transcript length)
    if "longestAudio" in (preferred, fallback):
        print("Computing durations for duration-based selection...")
        for f in files:
            get_duration(f, durations)

    mapping = load_map(cache, files, durations, excluded)

    if config.transcripts_xlsx:
        xlsx_path = directory / config.transcripts_xlsx
        added = import_xlsx_transcripts(xlsx_path, files, mapping)
        if added:
            print(f"Imported {added} transcripts from {xlsx_path}")
            mapping = sort_map(mapping, durations, excluded)
            save_json(cache, mapping)

    return VoiceInventory(files, mapping, durations)


def prepare(char, preferred, fallback, count, ids, do_transcribe, duration_target=None, top_n=0):
    config = CHARACTER_CONFIGS[char]
    count = config.count if count is None else count
    name = char.value
    workspace = CharacterWorkspace(DATA, name, config.category)
    excluded = set(config.exclude)
    selected_dir = workspace.selected
    cache = workspace.cache
    durations_path = workspace.durations
    inventory = prepare_sources(workspace, config, preferred, fallback)
    mapping = inventory.mapping

    top_done = 0
    if top_n:
        mapping, top_done = transcribe_top(
            inventory.files,
            mapping,
            cache,
            inventory.durations,
            excluded,
            top_n,
            workspace.generated / "asr_empty.json",
        )
        save_json(durations_path, inventory.durations)

    def make_request():
        return SelectionRequest(
            inventory.files,
            mapping,
            preferred,
            fallback,
            count,
            ids,
            excluded,
            list(config.selected),
            inventory.durations,
            duration_target,
        )

    selection = get_selection(selected_dir, make_request())
    save_json(durations_path, inventory.durations)

    transcribed = top_done
    if do_transcribe:
        # Transcribe only what the selection needs: untranscribed clips picked by the longestAudio
        # fallback. Then reselect, so longestText re-ranks with the new transcripts and the fallback
        # pulls in the next-longest untranscribed clip if still short. Stops when nothing is left to do.
        tried = set()
        while True:
            todo = [f for f in selection.files if not mapping.get(audio_id(f), "").strip() and audio_id(f) not in tried]
            if not todo:
                break
            parts = selection.method.split("+")
            if not any(p in ("longestAudio", "longestText") for p in parts):
                raise ValueError(
                    f"Refusing to transcribe: selection '{selection.method}' is not duration-based "
                    "(transcription is only for longestAudio/longestText flows)"
                )
            mapping = transcribe(todo, mapping, cache, inventory.durations, excluded)
            tried.update(audio_id(f) for f in todo)
            transcribed += sum(bool(mapping.get(audio_id(f), "").strip()) for f in todo)
            selection = get_selection(selected_dir, make_request())
        save_json(durations_path, inventory.durations)

    selected_files = selection.files
    method = selection.method

    missing = [audio_id(f) for f in selected_files if not mapping.get(audio_id(f), "").strip()]
    if missing:
        print("Selected files need transcripts:", ", ".join(missing))
        print(f"They have been copied to: {selected_dir}")
        status = "MISSING TRANSCRIPTS"
        length = None
    else:
        _, length = build_wav(selected_files, mapping, workspace, count, duration_target)
        print(f"JSON: {cache}")
        print(f"Selection method: {method}")
        status = "OK"

    return PreparationResult(
        character=name,
        status=status,
        selected=len(selected_files),
        method=method,
        transcribed=transcribed,
        missing=missing,
        length=length,
    )


def duration_targets_for_args(args):
    if args.min_duration is not None:
        return [DurationTarget(args.min_duration, "min")]
    if args.max_duration is not None:
        return [DurationTarget(args.max_duration, "max")]
    if args.count is not None:
        return [None]  # explicit --count with no duration flag: old count-based single file
    return [
        DurationTarget(DEFAULT_DUR_TARGET, "min"),
        DurationTarget(DEFAULT_DUR_TARGET, "max"),
    ]  # no options at all: build both defaults


def print_summary(results: list[PreparationResult]) -> None:
    headers = ("Character", "Variant", "Status", "Clips", "Method", "Transcribed", "Length")
    rows = []
    for r in results:
        m = re.match(r"^(.*) \((.*)\)$", r.character)
        name, variant = (m[1], m[2]) if m else (r.character, "")
        length = f"{r.length:.1f}s" if r.length is not None else "-"
        rows.append((name, variant, r.status, str(r.selected), r.method, str(r.transcribed), length))

    widths = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h) for i, h in enumerate(headers)]
    # numeric columns are right-aligned
    right = {3, 5, 6}

    def fmt(row):
        return "  ".join(
            (c.rjust(w) if i in right else c.ljust(w)) for i, (c, w) in enumerate(zip(row, widths, strict=True))
        ).rstrip()

    print("\n=== SUMMARY ===")
    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    last = None
    for row in rows:
        if last is not None and row[0] != last:
            print()
        last = row[0]
        print(fmt(row))

    for r in results:
        if r.missing:
            print(f"\n{r.character} missing transcripts: {', '.join(r.missing)}")


def build_mapping(raw, files):
    """Transcript map from raw subtitles.json data: normalised keys, cleaned text, gaps filled from filenames."""
    mapping = {}
    for k, v in raw.items():
        key = norm_key(k)
        text = clean_text(v)
        if text or not mapping.get(key, "").strip():
            mapping[key] = text
    for k, v in get_text(files).items():
        if not mapping.get(k, "").strip():
            mapping[k] = v
    return mapping


def transcribe_top(files, mapping, cache, durations, excluded, n, empty_path):
    """Make sure the n longest clips (by audio length) have transcripts. Idempotent: it is always the same
    n clips, so running it per variant or on later runs doesn't transcribe more. Clips ASR returned nothing
    for are remembered in asr_empty.json so they aren't retried every run."""
    ranked = sorted(files, key=lambda f: -get_duration(f, durations))[:n]
    empty = set(load_json(empty_path, []))
    todo = [f for f in ranked if not mapping.get(audio_id(f), "").strip() and audio_id(f) not in empty]
    if not todo:
        return mapping, 0
    print(f"Transcribing {len(todo)} of the {len(ranked)} longest clips...")
    mapping = transcribe(todo, mapping, cache, durations, excluded)
    done = [f for f in todo if mapping.get(audio_id(f), "").strip()]
    empty.update(audio_id(f) for f in todo if not mapping.get(audio_id(f), "").strip())
    save_json(empty_path, sorted(empty))
    return mapping, len(done)


def source_files(char):
    """(workspace, config, files) for a character without downloading anything; files is None if no audio."""
    config = CHARACTER_CONFIGS[char]
    workspace = CharacterWorkspace(DATA, char.value, config.category)
    directory = workspace.directory
    has_audio = directory.is_dir() and any(
        f.is_file() and workspace.generated not in f.parents and f.suffix.lower() in (".ogg", ".wav", ".mp3")
        for f in directory.rglob("*")
    )
    if not has_audio:
        return workspace, config, None
    try:
        files = [f for f in get_files(roots(directory), set(config.exclude)) if workspace.generated not in f.parents]
    except ValueError:
        return workspace, config, None
    return workspace, config, files


def cleanup_character(char, drop_orphans=False):
    """Rewrite one character's subtitles.json cleanly: normalised keys, cleaned text, filename transcripts
    filled in. Original is kept once as subtitles.json.bak. Orphans are kept unless drop_orphans."""
    workspace, config, files = source_files(char)
    result: dict[str, Any] = {
        "character": char.value,
        "status": "NO SOURCES",
        "keys": 0,
        "texts": 0,
        "orphans": 0,
        "dropped": 0,
    }
    if files is None:
        return result

    excluded = set(config.exclude)
    cache = workspace.cache
    raw = load_json(cache)
    if not isinstance(raw, dict):
        raw = {}

    mapping = build_mapping(raw, files)

    ids = {audio_id(f) for f in files}
    orphans = [k for k, v in mapping.items() if v.strip() and k not in ids and k not in excluded]
    result["orphans"] = len(orphans)
    if drop_orphans:
        for k in orphans:
            del mapping[k]
        result["dropped"] = len(orphans)
    for i in ids:
        mapping.setdefault(i, "")

    result["keys"] = sum(norm_key(k) != str(k).lower() for k in raw)
    result["texts"] = sum(clean_text(v) != str(v) for v in raw.values())
    mapping = sort_map(mapping, load_durations(workspace.durations), excluded)

    if mapping == raw:
        result["status"] = "ALREADY CLEAN"
        return result

    backup = cache.with_name(cache.name + ".bak")
    if cache.exists() and not backup.exists():
        shutil.copy2(cache, backup)
    save_json(cache, mapping)
    result["status"] = "CLEANED"
    return result


def print_cleanup(rows):
    print("\n=== CLEANUP ===")
    for r in rows:
        print(f"{r['character']}: {r['status']}")
        if r["status"] == "NO SOURCES":
            continue
        if r["status"] == "CLEANED":
            print(f"  Keys normalized: {r['keys']}  Texts cleaned: {r['texts']}")
        if r["dropped"]:
            print(f"  Orphan transcripts dropped: {r['dropped']}")
        elif r["orphans"]:
            print(f"  Orphan transcripts kept: {r['orphans']} (use --drop-orphans to remove them)")


def plan_character(char, preferred, fallback, count, ids, targets, top_n):
    """Dry run for one character: what --transcribe / --transcribe-top would transcribe. Writes nothing."""
    workspace, config, files = source_files(char)
    plan: dict[str, Any] = {
        "character": char.value,
        "status": "OK",
        "files": 0,
        "with_text": 0,
        "usable": 0,
        "top_n": 0,
        "variants": [],
    }
    if files is None:
        plan["status"] = "NO SOURCES"
        return plan

    excluded = set(config.exclude)
    raw = load_json(workspace.cache)
    if not isinstance(raw, dict):
        raw = {}
    mapping = build_mapping(raw, files)
    all_ids = {audio_id(f) for f in files}
    for i in all_ids:
        mapping.setdefault(i, "")
    durations = load_durations(workspace.durations)
    mapping = sort_map(mapping, durations, excluded)

    plan["files"] = len(all_ids)
    plan["with_text"] = sum(bool(mapping[i].strip()) for i in all_ids)
    plan["usable"] = sum(is_speech(mapping[i]) for i in all_ids)

    if top_n:
        ranked = sorted(files, key=lambda f: -get_duration(f, durations))[:top_n]
        empty = set(load_json(workspace.generated / "asr_empty.json", []))
        plan["top_n"] = sum(not mapping[audio_id(f)].strip() and audio_id(f) not in empty for f in ranked)

    for target in targets:
        label = workspace.wav_suffix(target, count)
        try:
            desired, method = select(
                SelectionRequest(
                    files, mapping, preferred, fallback, count, ids, excluded, list(config.selected), durations, target
                )
            )
            need = sum(not mapping[audio_id(f)].strip() for f in desired)
            plan["variants"].append((label, method, need, None))
        except Exception as e:
            plan["variants"].append((label, "-", 0, str(e)))
    return plan


def print_plan(plans, top_n):
    print("\n=== DRY RUN (nothing is transcribed or written) ===")
    total_top = total_sel = 0
    for p in plans:
        print(f"{p['character']}: {p['status']}")
        if p["status"] == "NO SOURCES":
            continue
        print(f"  Files: {p['files']}  Transcribed: {p['with_text']}  Usable speech: {p['usable']}")
        if top_n:
            print(f"  --transcribe-top {top_n}: would transcribe {p['top_n']} clips")
        need_max = 0
        for label, method, need, err in p["variants"]:
            if err:
                print(f"  {label}: cannot build ({err})")
                continue
            print(f"  {label}: {method}, {need} untranscribed clip(s) picked by the fallback")
            need_max = max(need_max, need)
        total_top += p["top_n"]
        total_sel += need_max
    if top_n:
        print(f"\nTotal: {total_top} clips from --transcribe-top, plus up to {total_sel} more from selection fallback")
    else:
        print(f"\nTotal with --transcribe: at least {total_sel} clips (more if new transcripts rank lower)")


def validate_character(char):  # noqa: C901
    """Read-only health check for one character: never downloads, transcribes or writes anything.
    Returns a dict describing key-matching / transcript problems.
    """
    config = CHARACTER_CONFIGS[char]
    workspace = CharacterWorkspace(DATA, char.value, config.category)
    directory = workspace.directory
    excluded = set(config.exclude)
    row: dict[str, Any] = {
        "character": char.value,
        "status": "OK",
        "files": 0,
        "with_text": 0,
        "missing": 0,
        "orphans": [],
        "legacy_keys": 0,
        "underscores": 0,
        "dup_ids": 0,
        "dup_detail": [],
        "usable": 0,
    }

    has_audio = directory.is_dir() and any(
        f.is_file() and workspace.generated not in f.parents and f.suffix.lower() in (".ogg", ".wav", ".mp3")
        for f in directory.rglob("*")
    )
    if not has_audio:
        row["status"] = "NO SOURCES"
        return row

    try:
        files = [f for f in get_files(roots(directory), excluded) if workspace.generated not in f.parents]
    except ValueError:
        row["status"] = "NO SOURCES"
        return row

    ids = [audio_id(f) for f in files]
    id_set = set(ids)
    row["files"] = len(id_set)
    row["dup_ids"] = len(ids) - len(id_set)
    if row["dup_ids"]:
        by_id = {}
        for f in files:
            by_id.setdefault(audio_id(f), []).append(str(f.relative_to(directory)))
        row["dup_detail"] = [(k, v) for k, v in by_id.items() if len(v) > 1]

    raw = load_json(workspace.cache)
    if not isinstance(raw, dict):
        raw = {}
    row["legacy_keys"] = sum(norm_key(k) != str(k).lower() for k in raw)
    row["underscores"] = sum("_" in str(v) for v in raw.values())

    mapping = {}
    for k, v in raw.items():
        key = norm_key(k)
        text = clean_text(v)
        if text or key not in mapping:
            mapping[key] = text
    for k, v in get_text(files).items():
        if not mapping.get(k, "").strip():
            mapping[k] = v

    row["orphans"] = sorted(k for k, v in mapping.items() if v.strip() and k not in id_set and k not in excluded)
    row["with_text"] = sum(bool(mapping.get(i, "").strip()) for i in id_set)
    row["missing"] = row["files"] - row["with_text"]
    row["usable"] = sum(is_speech(mapping.get(i, "")) for i in id_set)

    if row["orphans"] or row["dup_ids"]:
        row["status"] = "ISSUES"
    elif row["files"] and row["with_text"] == 0:
        row["status"] = "NO TRANSCRIPTS"
    elif row["legacy_keys"] or row["underscores"]:
        row["status"] = "NEEDS CLEANUP"  # auto-fixed the next time the character is run
    return row


def print_validation(rows):
    print("\n=== VALIDATION ===")
    for r in rows:
        print(f"{r['character']}: {r['status']}")
        if r["status"] == "NO SOURCES":
            continue
        print(
            f"  Files: {r['files']}  With transcript: {r['with_text']}  Missing: {r['missing']}"
            f"  Usable speech: {r['usable']}"
        )
        if r["legacy_keys"]:
            print(f"  Legacy keys (e.g. '.0b2' suffix, auto-normalized on next run): {r['legacy_keys']}")
        if r["underscores"]:
            print(f"  Transcripts containing '_' (auto-cleaned on next run): {r['underscores']}")
        if r["dup_ids"]:
            print(f"  Files sharing an audio id (collisions): {r['dup_ids']}")
            for k, names in r["dup_detail"][:5]:
                print(f"    {k}: {' | '.join(names)}")
        if r["orphans"]:
            print(f"  Transcripts matching no audio file: {len(r['orphans'])}, e.g. {', '.join(r['orphans'][:5])}")
    bad = [r["character"] for r in rows if r["status"] not in ("OK", "NO SOURCES")]
    print(f"\nNeed attention: {', '.join(bad) if bad else 'none'}")


def argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--selection",
        choices=["random", "longestAudio", "longestText", "selected", "alphabeticalText", "alphabeticalAudio"],
        default="longestText",
    )
    p.add_argument(
        "--fallback",
        choices=["random", "longestAudio", "longestText", "selected", "alphabeticalText", "alphabeticalAudio"],
        default="longestAudio",
    )
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--characters", nargs="+", choices=list(CHARACTER_CONFIGS), default=list(CHARACTER_CONFIGS)[:1])
    p.add_argument("--ids", nargs="*", default=[])
    p.add_argument("--all", action="store_true", help="Run every character")
    p.add_argument(
        "--cleanup",
        action="store_true",
        help="Only clean subtitles.json for the chosen characters (normalize keys, clean text, fill filename transcripts). Backs up the original once as subtitles.json.bak. Nothing is downloaded or transcribed.",
    )
    p.add_argument(
        "--drop-orphans", action="store_true", help="With --cleanup: also delete transcripts that match no audio file."
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help="Read-only check of transcript/key-matching problems for the chosen characters (use with --all). Nothing is downloaded, transcribed or written.",
    )
    p.add_argument(
        "--transcribe",
        action="store_true",
        help="Fill missing voice-reference transcripts with Qwen3-ASR 1.7B via llama.cpp",
    )
    p.add_argument(
        "--transcribe-top",
        type=int,
        default=0,
        metavar="N",
        help="Before selecting, make sure the N longest clips (by audio length) have transcripts, so longestText ranks over a real pool. Idempotent. Implies --transcribe.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many clips --transcribe / --transcribe-top would transcribe, per character. Nothing is transcribed, downloaded or written.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Recreate output even if the target wav already exists. Without this, any (character, variant) whose wav is already on disk is skipped entirely - no re-download, re-transcribe, or re-selection.",
    )

    dur = p.add_mutually_exclusive_group()
    dur.add_argument(
        "--min-duration",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Ignore --count; add clips in --selection/--fallback order until the total is at least this many seconds (the clip that crosses the line is kept).",
    )
    dur.add_argument(
        "--max-duration",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Ignore --count; add clips in --selection/--fallback order and stop before the total would exceed this many seconds (the clip that would push it over is dropped).",
    )

    return p


def main():  # noqa: C901
    p = argument_parser()
    a = p.parse_args()

    if a.all:
        a.characters = list(CHARACTER_CONFIGS)

    if a.drop_orphans:
        a.cleanup = True  # --drop-orphans on its own used to be silently ignored

    if a.cleanup:
        print_cleanup([cleanup_character(str(v), a.drop_orphans) for v in a.characters])
    if a.validate:
        print_validation([validate_character(str(v)) for v in a.characters])
    if a.transcribe_top:
        a.transcribe = True

    if a.dry_run:
        targets = duration_targets_for_args(a)
        plans = []
        for v in a.characters:
            char = str(v)
            config = CHARACTER_CONFIGS[char]
            count = config.count if a.count is None else a.count
            plans.append(
                plan_character(
                    char,
                    config.selection or a.selection,
                    config.fallback or a.fallback,
                    count,
                    a.ids,
                    targets,
                    a.transcribe_top,
                )
            )
        print_plan(plans, a.transcribe_top)

    if a.cleanup or a.validate or a.dry_run:
        return

    duration_targets = duration_targets_for_args(a)

    results = []

    for value in a.characters:
        name = str(value)
        config = CHARACTER_CONFIGS[name]
        workspace = CharacterWorkspace(DATA, name, config.category)
        count = config.count if a.count is None else a.count

        for duration_target in duration_targets:
            variant = workspace.wav_suffix(duration_target, count)
            print(f"\n=== {name} ({variant}) ===")

            out_path = workspace.wav_path(duration_target, count)
            if out_path.is_file() and not a.force:
                print(f"Skipping - already exists: {out_path}")
                print("(use --force to recreate)")
                results.append(
                    PreparationResult(
                        character=f"{name} ({variant})",
                        status="SKIPPED (exists)",
                        selected=0,
                        method="-",
                        transcribed=0,
                        missing=[],
                        length=None,
                    )
                )
                continue

            try:
                result = prepare(
                    name,
                    config.selection or a.selection,
                    config.fallback or a.fallback,
                    a.count,
                    a.ids,
                    a.transcribe,
                    duration_target,
                    a.transcribe_top,
                )
                result.character = f"{name} ({variant})"
                results.append(result)
            except Exception:
                traceback.print_exc()
                results.append(
                    PreparationResult(
                        character=f"{name} ({variant})",
                        status="FAILED",
                        selected=0,
                        method="-",
                        transcribed=0,
                        missing=[],
                        length=None,
                    )
                )

    print_summary(results)


if __name__ == "__main__":
    main()
