"""Print the agent restrictions, read from their owners instead of restated here.

`python -m scripts.review.checks.restrictions` numbers every row of the enforced-limit table in
[.agents/RESTRICTIONS.md]. `--all` adds the process-failure rows from [.agents/FAILURES.md] and the
harness rules from [.agents/DEEPSEEK-HARNESS.md]. The prose stays in those files; this command only
renders it, so it reads and never judges, and always exits 0.
"""

import argparse
import posixpath
import re
import sys
from pathlib import Path

from scripts.config import project_config as project_cfg

RESTRICTIONS = Path(".agents/RESTRICTIONS.md")
FAILURES = Path(".agents/FAILURES.md")
HARNESS = Path(".agents/DEEPSEEK-HARNESS.md")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
DASHES = re.compile(r":?-+:?")


def cells(line: str) -> list[str]:
    """One Markdown table row's columns, without the outer pipes."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator(row: list[str]) -> bool:
    """The `| --- |` row that marks a header, which is formatting rather than a rule."""
    return bool(row) and all(DASHES.fullmatch(cell) for cell in row)


def tables(path: Path) -> list[list[list[str]]]:
    """Every table in a document, each as its header followed by its rows."""
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("|"):
            row = cells(line)
            if not is_separator(row):
                current.append(row)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def resolve(text: str, folder: Path) -> str:
    """A relative Markdown link becomes the path it points at, so the terminal says where to read."""

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if "://" in target:
            return f"{label} {target}"
        return f"{label} ({posixpath.normpath(f'{folder.as_posix()}/{target}')})"

    return LINK.sub(replace, text)


def print_tables(path: Path, start: int = 1) -> int:
    """Number every row from `start`, labeling the remaining columns by their header; returns the count."""
    print(f"\n### {path.stem.replace('-', ' ').title()} ({path.as_posix()})")
    printed = start - 1
    for table in tables(project_cfg.BASE_DIR / path):
        labels = [header.lower() for header in table[0][1:]]
        for row in table[1:]:
            printed += 1
            print(f"{printed:2}. {resolve(row[0], path.parent)}")
            for label, value in zip(labels, row[1:], strict=False):
                print(f"    {label}: {resolve(value, path.parent)}")
    return printed - start + 1


def print_harness(start: int = 1) -> int:
    """The harness page's rule bullets as they are written, since its prose is already the owner."""
    print(f"\n### Harness rules ({HARNESS.as_posix()})")
    rules = [
        line.removeprefix("- ")
        for line in (project_cfg.BASE_DIR / HARNESS).read_text(encoding="utf-8-sig").splitlines()
        if line.startswith("- ")
    ]
    for offset, rule in enumerate(rules):
        print(f"{start + offset:2}. {rule}")
    return len(rules)


def main(argv: list[str] | None = None) -> int:
    """Render the restriction table, and with `--all` the failure and harness rules too."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="add the process-failure rows and the harness rules")
    args = parser.parse_args(argv)
    # - a redirected console is not UTF-8 by default, and the owner prose carries an arrow
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    printed = print_tables(RESTRICTIONS)
    if args.all:
        printed += print_tables(FAILURES, start=printed + 1)
        printed += print_harness(start=printed + 1)
    print(f"\n[OK] {printed} restrictions printed; owners: {RESTRICTIONS.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
