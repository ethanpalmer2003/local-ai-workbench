"""One place that decides whether a run is long enough to need the user's agreement.

A run expected to pass `LONG_RUN_SECONDS` asks the person at the terminal. An agent or a scheduled
job has nobody to answer, so silence is a refusal and `--yes` is only for a run the user asked for.
Shorter runs never ask, because a scoped gate and the suite finish in seconds and asking there only
trains the reader to answer without looking.

Two kinds of entry point stay out of the duration rule. A launcher starts a service the person then
uses, so a prompt would land in a double-clicked window that nobody watches; and a tool that only
reads or reports has nothing to agree to. Destructive tools carry their own `--apply` or `--dry-run`
default instead, which is a better question than a duration, and an irreversible stop uses
`confirm`, which asks every time.
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


def _agree(prompt: str, refusal: str) -> bool:
    """The one prompt: a person types yes, and anything else, including a closed stdin, refuses."""
    if sys.stdin.isatty():
        print(prompt, flush=True)
        # - readline, not input: a captured or closed stdin answers nothing, which is a refusal
        if sys.stdin.readline().strip().lower() == "yes":
            return True
    print(refusal, flush=True)
    return False


def ask(what: str, expected_seconds: float, given: bool = False) -> bool:
    """Whether `what` may start: a short run always may, a long one needs `--yes` or an answer."""
    if not is_long(expected_seconds) or given:
        return True
    minutes = _minutes(expected_seconds)
    return _agree(
        f"{what} takes about {minutes}. Type yes to continue:",
        f"[FAIL] {what} takes about {minutes}; pass --yes when the user asked for it.",
    )


def confirm(what: str, given: bool = False) -> bool:
    """Whether an irreversible action may run: it always asks, because its cost is not time."""
    if given:
        return True
    return _agree(
        f"{what}. Type yes to continue:", f"[FAIL] {what} needs a yes; pass --yes when the user asked for it."
    )


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
    """Add the `--yes` that lets an unattended long run or an irreversible action start."""
    parser.add_argument(
        "--yes", action="store_true", help="confirm a run that takes minutes or stops something; otherwise ask"
    )
