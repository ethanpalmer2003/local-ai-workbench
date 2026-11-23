"""Reference-clip quality for the clone voices: sound annotations, scene text and broken characters."""

from typing import TypedDict

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp_catalog

# - a clone speaks the reference clip, so a transcript naming a sound teaches the model that sound
SOUND_TOKENS = ("cough", "laugh", "sigh", "giggle", "scream", "breathe", "chuckle", "gasp", "yawn", "groan", "moan")
SCENE_MARKS = ("[", "]", "(", ")", "*")
BROKEN_CHARACTERS = ("\ufffd", "Ã", "â€")


class Row(TypedDict):
    voice: str
    clip: str
    problems: list[str]


def problems(transcript: str) -> list[str]:
    """Why a reference transcript is unfit to clone from; empty when it reads as plain speech."""
    found: list[str] = []
    lowered = transcript.lower()
    sounds = [token for token in SOUND_TOKENS if token in lowered]
    if sounds:
        found.append("sound annotation: " + ", ".join(sounds))
    if any(mark in transcript for mark in SCENE_MARKS):
        found.append("scene direction brackets")
    if any(mark in transcript for mark in BROKEN_CHARACTERS):
        found.append("broken characters")
    return found


def report() -> list[Row]:
    """One row per configured clone voice: its chosen clip and what makes that clip unfit, if anything."""
    rows: list[Row] = []
    for voice in cfg.AUDIOCPP_PROXY_CLONE_VOICES:
        reference = audiocpp_catalog.resolve_voice_ref(voice)
        if reference is None:
            rows.append({"voice": voice, "clip": "", "problems": ["no reference clip"]})
            continue
        clip, transcript = reference
        rows.append({"voice": voice, "clip": clip, "problems": problems(str(transcript))})
    return rows


def main() -> int:
    """Print every reference that needs regenerating; the private overlay owns the audio itself."""
    rows = report()
    flagged = [row for row in rows if row["problems"]]
    for row in flagged:
        print(f"[WARN] {row['voice']}: {'; '.join(str(item) for item in row['problems'])} -> {row['clip']}")
    print(f"[OK] {len(rows) - len(flagged)} of {len(rows)} clone references read as plain speech")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
