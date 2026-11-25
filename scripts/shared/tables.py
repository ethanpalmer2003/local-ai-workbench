"""Aligned console tables and status fields: the renderers a plan or listing prints through."""

from collections.abc import Sequence


def render_fields(fields: Sequence[tuple[str, str]]) -> str:
    """Aligned `label: value` lines for a status block; a table would be a header for two rows."""
    width = max((len(label) for label, _value in fields), default=0)
    return "\n".join(f"{label.ljust(width)}: {value}" for label, value in fields)


def render_table(rows: Sequence[Sequence[str]], columns: Sequence[str]) -> str:
    """One aligned table: every column as wide as its widest cell, so a plan scans by row."""
    cells = [[row[index] if index < len(row) else "" for index in range(len(columns))] for row in rows]
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in cells)) if cells else len(columns[index])
        for index in range(len(columns))
    ]

    def line(values: Sequence[str]) -> str:
        return "| " + " | ".join(value.ljust(widths[index]) for index, value in enumerate(values)) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([line(columns), separator, *(line(row) for row in cells)])
