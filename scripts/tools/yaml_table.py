"""Print a YAML list of mappings as a table.

The data files this workspace keeps by hand - parked work, the input overlay, voice sources - are already
lists of records. Rendering one is a read, not a generation step: nothing is computed, so no page has to
stay in step with it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from tabulate import tabulate


def read(path: Path) -> list[dict[str, str]]:
    """The records in a YAML file, flattened to text so every column prints."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} must hold a list of mappings")
    entries = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path.name} entry {index} must be a mapping")
        entries.append({str(key): "" if value is None else str(value) for key, value in item.items()})
    return entries


def columns(entries: list[dict[str, Any]], requested: list[str] | None = None) -> list[str]:
    """The requested keys, or every key in the order the first record introduces it."""
    if requested:
        return requested
    seen: dict[str, None] = {}
    for entry in entries:
        for key in entry:
            seen.setdefault(key, None)
    return list(seen)


def render(entries: list[dict[str, Any]], requested: list[str] | None = None, fmt: str = "simple") -> str:
    keys = columns(entries, requested)
    rows = [[str(entry.get(key, "")) for key in keys] for entry in entries]
    return tabulate(rows, headers=keys, tablefmt=fmt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="YAML file holding a list of mappings")
    parser.add_argument("--columns", help="comma-separated keys in print order; default is every key seen")
    parser.add_argument("--markdown", action="store_true", help="emit a Markdown table instead of plain text")
    args = parser.parse_args(argv)
    requested = [name.strip() for name in args.columns.split(",")] if args.columns else None
    try:
        entries = read(args.path)
    except ValueError as error:
        parser.error(str(error))
    print(render(entries, requested, "github" if args.markdown else "simple"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
