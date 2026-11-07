"""
Quickly sweep SILENCE_NOISE_DB / SILENCE_MIN_DUR combos against the mp3.

- Reports how many silences each combo finds
- Does not touch MAX_MERGED_DUR or export any clips
- Use to dial in the two silence settings, then copy values into split_from_csv.py
- Usage: `python -m scripts.download.input.tune_silence --voice <id>`
"""

import argparse
import re
import subprocess

from scripts.config import overlay_inputs as inputs
from scripts.download.input.audio_workflow import MIN_DUR_VALUES, NOISE_DB_VALUES, source_paths


def detect_silences(mp3_path, noise_db, min_dur):
    result = subprocess.run(
        ["ffmpeg", "-i", str(mp3_path), "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", result.stderr)]
    return len(starts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default=inputs.default_voice())
    args = parser.parse_args()
    paths = source_paths(args.voice)

    print(f"{'noise_db':>10} {'min_dur':>8} {'silences_found':>15}")
    for noise_db in NOISE_DB_VALUES:
        for min_dur in MIN_DUR_VALUES:
            count = detect_silences(paths.media_path, noise_db, min_dur)
            print(f"{noise_db:>10} {min_dur:>8} {count:>15}")


if __name__ == "__main__":
    main()
