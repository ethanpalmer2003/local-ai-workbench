"""A token that one module owns must not be spelled anywhere else.

Each row is a literal that describes one rule, plus the files allowed to name it. Copying the
literal into a second module is how a rule drifts: the consent flag was spelled by three callers
before `consent.take` owned it, and every copy had to be kept in step by hand. The table is the
place to record a token when a rule becomes single-owner; a new copy then fails the gate instead of
passing review unnoticed.
"""

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.file_sets import maintained_files


@dataclass(frozen=True)
class Rule:
    """One literal, the files that may name it, and why it is single-owner."""

    token: str
    owners: frozenset[str]
    reason: str


RULES: tuple[Rule, ...] = (
    Rule(
        "--yes",
        frozenset(
            {
                "scripts/review/checks/owned_tokens.py",
                "scripts/shared/consent.py",
                "scripts/tests/validate.py",
                "bat/manage/manage_kill_ai_services.bat",
                "bat/update_frameworks.bat",
            }
        ),
        "the unattended answer lives in consent.flag/take/forward; validate forwards it to staged runs and a "
        "double-clicked batch is the request it carries",
    ),
)


def _relative(path) -> str:
    try:
        return path.relative_to(project_cfg.BASE_DIR).as_posix()
    except ValueError:
        # - a caller can hand in a scratch file, and the report still has to name it
        return path.as_posix()


def _python_strings(path) -> list[tuple[str, int]]:
    """Every string literal with its line, so a docstring mention inside the owner still counts."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [
        (node.value, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _text_lines(path) -> list[tuple[str, int]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [(line, number) for number, line in enumerate(text.splitlines(), start=1)]


def findings(paths: list[Path] | None = None, rules: tuple[Rule, ...] = RULES) -> list[tuple[str, str, int]]:
    """Every mention of a single-owner token outside its owners, as (token, path, line)."""
    found: list[tuple[str, str, int]] = []
    for path in maintained_files() if paths is None else paths:
        if path.suffix.lower() not in {".py", ".bat"}:
            continue
        relative = _relative(path)
        if relative.startswith("scripts/tests/cases/"):
            # - a test spells the token to assert what the owner does; that is not a second copy
            continue
        literals = _python_strings(path) if path.suffix.lower() == ".py" else _text_lines(path)
        for rule in rules:
            if relative in rule.owners:
                continue
            found.extend((rule.token, relative, line) for text, line in literals if rule.token in text)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the single-owner table and stop")
    args = parser.parse_args(argv)
    if args.list:
        for rule in RULES:
            print(f"{rule.token}: {', '.join(sorted(rule.owners))} ({rule.reason})")
        return 0
    problems = findings()
    for token, relative, line in problems:
        owners = ", ".join(sorted(next(rule for rule in RULES if rule.token == token).owners))
        print(f"[FAIL] {token!r} appears in {relative}:{line}; owner is {owners}")
    if problems:
        return 1
    print(f"[OK] {len(RULES)} single-owner token(s) stay in their owners")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
