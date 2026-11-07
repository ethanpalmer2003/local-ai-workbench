"""
Split a full-length mp3 into per-line clips using a Start,Duration,Text CSV.

- Clips named by ID only (0000.wav, 0001.wav, ...)
- Full transcripts go into subtitles.json instead of the filename
  - Windows' ~260 char path limit makes long merged sentences unsafe in a filename
- get_tts_voices.py's load_map() reads subtitles.json first, falls back to
  filename-derived text for missing IDs
  - Drop-in fit for the existing pipeline - no changes needed there
- This caption format's Start/Duration values overlap almost everywhere
  ("Duration" is an estimate, not a measured end)
  - No usable gap in the CSV itself to detect real pauses
  - Instead: run ffmpeg's silencedetect on the mp3 once, cache results,
    use actual detected silence to decide where a merged "sentence" ends
- MAX_MERGED_DUR is a hard cap so a spot with no detected silence at all
  can't turn into one giant clip
- Usage: `python -m scripts.download.input.split_from_csv --voice <id>`; the source recording,
  CSV and outputs live under `<input>/audio/<id>/source`
"""

import argparse
import contextlib
import csv
import json
import re
import subprocess

from scripts.config import inputs
from scripts.download.input.audio_workflow import MAX_MERGED_DUR, SILENCE_MIN_DUR, SILENCE_NOISE_DB, source_paths


def detect_silences(mp3_path, noise_db, min_dur, cache_path):
    """Run ffmpeg's silencedetect once and cache (start, end) pairs to disk.

    - Reuse only when source identity and settings match
    """
    source = mp3_path.stat()
    cache_key = [str(mp3_path.resolve()), source.st_size, source.st_mtime_ns, noise_db, min_dur]
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("key") == cache_key:
                print(f"Using cached silence detection ({len(cached['silences'])} pauses)")
                return [tuple(p) for p in cached["silences"]]
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"Scanning for silence (noise={noise_db}dB, min_dur={min_dur}s) - this reads the whole file once...")
    result = subprocess.run(
        ["ffmpeg", "-i", str(mp3_path), "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )

    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", result.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", result.stderr)]
    silences = list(zip(starts, ends))

    print(f"Found {len(silences)} silent stretches")
    cache_path.write_text(json.dumps({"key": cache_key, "silences": silences}, indent=2), encoding="utf-8")
    return silences


def has_silence_between(t1, t2, silences):
    """True if any detected silence overlaps the window [t1, t2].

    - Overlap test: s_start < t2 and s_end > t1
    """
    return any(s_start < t2 and s_end > t1 for s_start, s_end in silences)


def merge_rows(rows, silences, max_dur=MAX_MERGED_DUR):
    """Collapse consecutive CSV rows into sentence-ish groups.

    - Boundary placed between two rows if:
      - Real detected silence falls in the window between them, or
      - Group has run past max_dur with no silence found at all
    - A clip's end is always the next clip's Start
      - Row Start timestamps are reliable even though Duration values overlap
      - Adjacent clips never overlap or leave a gap
    - Returns (merged_clips, silence_boundary_count, cap_boundary_count)
      so the caller can report which mechanism is doing the splitting
    """
    if not rows:
        return [], 0, 0

    boundaries = [0]
    group_start_idx = 0
    silence_cuts = 0
    cap_cuts = 0

    for i in range(1, len(rows)):
        prev_start = float(rows[i - 1]["Start"])
        cur_start = float(rows[i]["Start"])
        elapsed = cur_start - float(rows[group_start_idx]["Start"])

        by_silence = has_silence_between(prev_start, cur_start, silences)
        by_cap = elapsed > max_dur

        if by_silence or by_cap:
            boundaries.append(i)
            group_start_idx = i
            if by_silence:
                silence_cuts += 1
            else:
                cap_cuts += 1

    boundaries.append(len(rows))

    merged = []
    for s_idx, e_idx in zip(boundaries, boundaries[1:]):
        start = float(rows[s_idx]["Start"])
        if e_idx < len(rows):
            end = float(rows[e_idx]["Start"])
        else:
            last = rows[-1]
            end = float(last["Start"]) + float(last["Duration"])
        text = " ".join(rows[j]["Text"].strip() for j in range(s_idx, e_idx))
        merged.append((start, end - start, text))

    return merged, silence_cuts, cap_cuts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default=inputs.default_voice(), help="voice id under the input overlay")
    args = parser.parse_args()
    paths = source_paths(args.voice)
    paths.out_dir.mkdir(parents=True, exist_ok=True)

    with paths.csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    silences = detect_silences(paths.media_path, SILENCE_NOISE_DB, SILENCE_MIN_DUR, paths.silence_cache_path)

    grouped, silence_cuts, cap_cuts = merge_rows(rows, silences)
    print(f"Merged {len(rows)} raw rows -> {len(grouped)} sentence-ish clips")
    print(f"  boundaries from detected silence: {silence_cuts}")
    print(f"  boundaries from MAX_MERGED_DUR cap: {cap_cuts}")
    if silence_cuts == 0:
        print(
            "  -> no real pauses detected at all; every cut is an arbitrary MAX_MERGED_DUR cap. Try raising SILENCE_NOISE_DB (e.g. -20 or -15) - background music/noise is likely never dipping below the current threshold."
        )
    print()

    subtitles = {}
    with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
        subtitles = json.loads(paths.subtitles_path.read_text(encoding="utf-8"))

    for i, (start, dur, text) in enumerate(grouped):
        key = f"{i:04d}"
        if not text.strip():
            print(f"[{key}] skipped (empty text)")
            continue

        out_path = paths.out_dir / f"{key}.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-t",
                str(dur),
                "-i",
                str(paths.media_path),
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(out_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subtitles[key] = text
        print(f"[{key}] {text[:70]}{'...' if len(text) > 70 else ''}")

    paths.subtitles_path.write_text(json.dumps(subtitles, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nDone: {len(grouped)} clips -> {paths.out_dir}")
    print(f"Transcripts written -> {paths.subtitles_path}")


if __name__ == "__main__":
    main()
