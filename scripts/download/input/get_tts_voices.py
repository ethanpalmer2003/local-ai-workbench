"""The voice preparation command line: argument parsing and the per-character run."""

import argparse
import traceback
from typing import Any

from scripts.download.input.voice_model import CHARACTER_CONFIGS, DATA, CharacterWorkspace, PreparationResult
from scripts.download.input.voice_workflow import (
    cleanup_character,
    duration_targets_for_args,
    plan_character,
    prepare,
    print_cleanup,
    print_plan,
    print_summary,
    print_validation,
    validate_character,
)


def argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--selection",
        choices=["random", "longestAudio", "longestText", "pinned", "alphabeticalText", "alphabeticalAudio"],
        default="longestText",
    )
    p.add_argument(
        "--fallback",
        choices=["random", "longestAudio", "longestText", "pinned", "alphabeticalText", "alphabeticalAudio"],
        default="longestAudio",
    )
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--characters", nargs="+", choices=list(CHARACTER_CONFIGS), default=list(CHARACTER_CONFIGS)[:1])
    p.add_argument("--all", action="store_true", help="Run every character")
    p.add_argument(
        "--cleanup",
        action="store_true",
        help="Only clean subtitles.json for the chosen characters (normalize keys, clean text, fill filename "
        "transcripts). "
        "Backs up the original once as subtitles.json.bak. Nothing is downloaded or transcribed.",
    )
    p.add_argument(
        "--drop-orphans", action="store_true", help="With --cleanup: also delete transcripts that match no audio file."
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help="Read-only check of transcript/key-matching problems for the chosen characters (use with --all). Nothing "
        "is downloaded, transcribed or written.",
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
        help="Before selecting, make sure the N longest clips (by audio length) have transcripts, so longestText ranks "
        "over a real pool. Idempotent. Implies --transcribe.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many clips --transcribe / --transcribe-top would transcribe, per character. Nothing is "
        "transcribed, "
        "downloaded or written.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Recreate output even if the target wav already exists. Without this, any (character, variant) whose wav "
        "is already on disk is skipped entirely - no re-download, re-transcribe, or re-selection.",
    )

    dur = p.add_mutually_exclusive_group()
    dur.add_argument(
        "--min-duration",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Ignore --count; add clips in --selection/--fallback order until the total is at least this many seconds "
        "(the clip that crosses the line is kept).",
    )
    dur.add_argument(
        "--max-duration",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Ignore --count; add clips in --selection/--fallback order and stop before the total would exceed this "
        "many seconds (the clip that would push it over is dropped).",
    )

    return p


def _planned(a, targets) -> list[Any]:
    plans = []
    for v in a.characters:
        char = str(v)
        config = CHARACTER_CONFIGS[char]
        count = config.count if a.count is None else a.count
        plans.append(
            plan_character(
                char, config.selection or a.selection, config.fallback or a.fallback, count, targets, a.transcribe_top
            )
        )
    return plans


def _read_only_actions(a) -> bool:
    """Run --cleanup/--validate/--dry-run; True when nothing else should run."""
    if a.drop_orphans:
        a.cleanup = True  # --drop-orphans on its own used to be silently ignored
    if a.cleanup:
        print_cleanup([cleanup_character(str(v), a.drop_orphans) for v in a.characters])
    if a.validate:
        print_validation([validate_character(str(v)) for v in a.characters])
    if a.transcribe_top:
        a.transcribe = True
    if a.dry_run:
        print_plan(_planned(a, duration_targets_for_args(a)), a.transcribe_top)
    return a.cleanup or a.validate or a.dry_run


def _prepare_variant(a, name: str, config, duration_target) -> PreparationResult:
    workspace = CharacterWorkspace(DATA, name, config.category)
    count = config.count if a.count is None else a.count
    variant = workspace.wav_suffix(duration_target, count)
    print(f"\n=== {name} ({variant}) ===")

    out_path = workspace.wav_path(duration_target, count)
    if out_path.is_file() and not a.force:
        print(f"Skipping - already exists: {out_path}")
        print("(use --force to recreate)")
        return PreparationResult(
            character=f"{name} ({variant})",
            status="SKIPPED (exists)",
            selected=0,
            method="-",
            transcribed=0,
            missing=[],
            length=None,
        )

    try:
        result = prepare(
            name,
            config.selection or a.selection,
            config.fallback or a.fallback,
            a.count,
            a.transcribe,
            duration_target,
            a.transcribe_top,
        )
        result.character = f"{name} ({variant})"
        return result
    except Exception:
        traceback.print_exc()
        return PreparationResult(
            character=f"{name} ({variant})",
            status="FAILED",
            selected=0,
            method="-",
            transcribed=0,
            missing=[],
            length=None,
        )


def _prepare_all(a, duration_targets) -> list[PreparationResult]:
    results = []
    for value in a.characters:
        name = str(value)
        config = CHARACTER_CONFIGS[name]
        for duration_target in duration_targets:
            results.append(_prepare_variant(a, name, config, duration_target))
    return results


def main():
    p = argument_parser()
    a = p.parse_args()

    if a.all:
        a.characters = list(CHARACTER_CONFIGS)

    if _read_only_actions(a):
        return

    print_summary(_prepare_all(a, duration_targets_for_args(a)))


if __name__ == "__main__":
    main()
