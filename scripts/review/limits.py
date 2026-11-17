"""Every numeric rule in one place: the limit, the current edge, and the exceptions each one accepts.

A reader asking "how close is this to the limit" or "what is exempt right now" should not have to open
five checks. Each row names its owner, prints the thresholds, and lists the items sitting in the band
between the warning and the failure. Run it before raising a limit: the borderline list is what the
change would let through.
"""

import argparse
import json

from scripts.config import project_config as project_cfg
from scripts.review.checks import annotations as annotation_check
from scripts.review.checks import bare_any, inventory_code, line_length, owned_tokens

DUPLICATE_BASELINE = project_cfg.SCRIPTS_DIR / "review" / "lists" / "duplicate-baseline.json"


def duplicate_baseline() -> tuple[int, int]:
    """(pairs, blocks) accepted by the duplicate check."""
    if not DUPLICATE_BASELINE.is_file():
        return 0, 0
    pairs = json.loads(DUPLICATE_BASELINE.read_text(encoding="utf-8"))["pairs"]
    return len(pairs), sum(int(count) for count in pairs.values())


def borderline_annotations() -> list[annotation_check.Annotation]:
    """Annotations in the band a stricter limit would catch: at the warning or above."""
    return annotation_check.findings()


def report() -> list[str]:
    """The whole rules table plus the detail a limit change would need."""
    folders, source_files = inventory_code.repository_inventory(project_cfg.BASE_DIR)
    folder_ends = inventory_code.folder_validation(folders)
    baseline = inventory_code.load_file_baseline()
    file_ends = inventory_code.file_lengths(source_files, baseline)
    watched = borderline_annotations()
    over_annotations = [
        item for item in watched if item.score > annotation_check.MAX_SCORE or item.depth > annotation_check.MAX_DEPTH
    ]
    accepted_duplicates = duplicate_baseline()
    lines = [
        "# Rule limits",
        "",
        f"{'rule':<16} {'owner':<24} {'limit':<34} now",
        f"{'-' * 16} {'-' * 24} {'-' * 34} {'-' * 30}",
        f"{'line length':<16} {'checks/line_length.py':<24} "
        f"{f'{line_length.LIMIT} characters':<34} {len(line_length.findings())} to wrap, "
        f"{sum(line_length.accepted().values())} accepted lines",
        f"{'annotations':<16} {'checks/annotations.py':<24} "
        f"{f'{annotation_check.WARN_SCORE} warn / {annotation_check.MAX_SCORE} fail':<34} "
        f"{len(watched)} under watch, {len(over_annotations)} over, depth {annotation_check.MAX_DEPTH}",
        f"{'folders':<16} {'checks/inventory_code.py':<24} "
        f"{f'{inventory_code.MIN_FOLDER_ITEMS} / {inventory_code.MAX_FOLDER_ITEMS} direct files':<34} "
        f"{len(folder_ends.crowded)} over, {len(folder_ends.single)} single-file",
        f"{'file length':<16} {'checks/inventory_code.py':<24} "
        f"{f'{inventory_code.WARN_FILE_LINES} warn / {inventory_code.MAX_FILE_LINES} fail':<34} "
        f"{len(file_ends.long)} over the warning, {len(file_ends.over) - len(file_ends.blocked)} accepted",
        f"{'bare Any':<16} {'checks/bare_any.py':<24} "
        f"{'no bare signature Any':<34} {len(bare_any.findings())} signature(s) in code",
        f"{'owned tokens':<16} {'checks/owned_tokens.py':<24} "
        f"{'one spelling per token':<34} {len(owned_tokens.RULES)} token(s), "
        f"{sum(len(rule.owners) for rule in owned_tokens.RULES)} accepted owners",
        f"{'duplicates':<16} {'checks/duplicates.py':<24} "
        f"{'reviewed baseline':<34} {accepted_duplicates[0]} pairs, {accepted_duplicates[1]} blocks accepted",
    ]
    lines.extend(("", "## Borderline annotations (what a stricter limit would catch)", ""))
    lines.extend(f"- {item}" for item in watched) if watched else lines.append("None.")
    if over_annotations:
        lines.extend(("", "Over the cap:", ""))
        lines.extend(f"- {item}" for item in over_annotations)
    lines.extend(("", "## Exceptions in force", ""))
    lines.extend(f"- owned token {rule.token!r}: {', '.join(sorted(rule.owners))}" for rule in owned_tokens.RULES)
    lines.extend(f"- accepted file: {path} ({length} lines)" for path, length in sorted(baseline.items()))
    if not baseline:
        lines.append("- no file-length exceptions")
    accepted = line_length.accepted()
    lines.extend(
        ("", f"{accepted['template']} template and {accepted['token']} token lines are exempt as string content")
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print("\n".join(report()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
