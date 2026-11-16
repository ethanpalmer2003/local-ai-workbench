"""One place that decides whether a run is long enough to need the user's agreement.

A run expected to pass `LONG_RUN_SECONDS` asks the person at the terminal. An agent or a scheduled
job has nobody to answer, so silence is a refusal and `--yes` is only for a run the user asked for.
Shorter runs never ask, because a scoped gate and the suite finish in seconds and asking there only
trains the reader to answer without looking.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# - the repository's approval bound for a single run, in seconds
LONG_RUN_SECONDS = 300


def is_long(expected_seconds: float) -> bool:
    """Whether a run of this expected length is one the person should agree to."""
    return expected_seconds >= LONG_RUN_SECONDS


def _minutes(expected_seconds: float) -> str:
    minutes = expected_seconds / 60
    return f"{minutes:.0f} min" if minutes >= 1 else f"{minutes:.1f} min"


def ask(what: str, expected_seconds: float, given: bool = False) -> bool:
    """Whether `what` may start: a short run always may, a long one needs `--yes` or an answer."""
    if not is_long(expected_seconds) or given:
        return True
    if sys.stdin.isatty():
        print(f"{what} takes about {_minutes(expected_seconds)}. Type yes to continue:", flush=True)
        # - readline, not input: a captured or closed stdin answers nothing, which is a refusal
        if sys.stdin.readline().strip().lower() == "yes":
            return True
    print(f"[FAIL] {what} takes about {_minutes(expected_seconds)}; pass --yes when the user asked for it.", flush=True)
    return False


def require(expected_seconds: float, what: str = "") -> None:
    """Ask before a hardcoded entry point starts; `--yes` anywhere in argv already answers.

    `--help` passes through untouched, because printing usage starts no work.
    """
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        return
    given = "--yes" in argv
    sys.argv[1:] = [argument for argument in argv if argument != "--yes"]
    if not ask(what or Path(sys.argv[0]).stem, expected_seconds, given):
        raise SystemExit(1)


def flag(parser: argparse.ArgumentParser) -> None:
    """Add the `--yes` that lets an unattended long run start."""
    parser.add_argument(
        "--yes", action="store_true", help="confirm a run that takes minutes; otherwise a person is asked"
    )
