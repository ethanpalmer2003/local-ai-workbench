"""Rewrite Python import paths after moving modules.

Run from C:/AI, for example:
  python -m scripts.tools.rewrite_imports --root scripts --move old.module=new.module

Only explicit module mappings are changed. Python import statements are parsed
before rewriting, and matching dotted paths in Python source are updated too.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from pathlib import Path
import re
import sys

EXCLUDED = {".git", ".venv", "__pycache__", "node_modules", "output", "state"}


def parse_moves(values: list[str]) -> dict[str, str]:
    moves = {}
    for value in values:
        old, separator, new = value.partition("=")
        if not separator or not old or not new:
            raise ValueError(f"Expected OLD.MODULE=NEW.MODULE, got {value!r}")
        if any(not part.isidentifier() for part in (*old.split("."), *new.split("."))):
            raise ValueError(f"Module paths must be dotted identifiers: {value!r}")
        if old in moves and moves[old] != new:
            raise ValueError(f"Conflicting mappings for {old!r}")
        moves[old] = new
    if not moves:
        raise ValueError("Provide at least one --move OLD.MODULE=NEW.MODULE")
    return moves


def remap(module: str, moves: dict[str, str]) -> str:
    for old in sorted(moves, key=len, reverse=True):
        if module == old or module.startswith(old + "."):
            return moves[old] + module[len(old) :]
    return module


def _alias_text(alias: ast.alias) -> str:
    return alias.name + (f" as {alias.asname}" if alias.asname else "")


def _from_statement(module: str, aliases: list[ast.alias]) -> str:
    return f"from {module} import {', '.join(_alias_text(alias) for alias in aliases)}"


def _rewrite_import(node: ast.Import | ast.ImportFrom, moves: dict[str, str]) -> str | None:
    if isinstance(node, ast.Import):
        if all(remap(alias.name, moves) == alias.name for alias in node.names):
            return None
        aliases = []
        for alias in node.names:
            name = remap(alias.name, moves)
            aliases.append(name + (f" as {alias.asname}" if alias.asname else ""))
        return "import " + ", ".join(aliases)

    if node.level or not node.module:
        return None

    mapped_module = remap(node.module, moves)
    if mapped_module != node.module:
        return _from_statement(mapped_module, node.names)

    groups: dict[str, list[ast.alias]] = defaultdict(list)
    for alias in node.names:
        if alias.name == "*":
            groups[node.module].append(alias)
            continue
        full_name = f"{node.module}.{alias.name}"
        mapped_name = remap(full_name, moves)
        if mapped_name == full_name:
            groups[node.module].append(alias)
        else:
            parent, leaf = mapped_name.rsplit(".", 1)
            groups[parent].append(ast.alias(name=leaf, asname=alias.asname))

    if len(groups) == 1 and node.module in groups:
        return None
    return "\n".join(_from_statement(module, aliases) for module, aliases in groups.items())


def rewrite_file(path: Path, moves: dict[str, str], *, dry_run: bool) -> bool:
    with path.open("r", encoding="utf-8", newline="") as stream:
        source = stream.read()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        print(f"[WARN] Skipped unparsable Python: {path}: {error}")
        return False

    lines = source.splitlines(keepends=True)
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        old_text = ast.get_source_segment(source, node)
        if not old_text:
            continue
        new_text = _rewrite_import(node, moves)
        if new_text is None:
            continue
        if "#" in old_text:
            print(f"[WARN] Import comment needs manual review: {path}:{node.lineno}")
            continue
        indent = lines[node.lineno - 1][: len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())]
        newline = "\r\n" if "\r\n" in source else "\n"
        replacement = [indent + item + newline for item in new_text.splitlines()]
        edits.append((node.lineno - 1, node.end_lineno, replacement))

    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = replacement
    updated = "".join(lines)

    for old in sorted(moves, key=len, reverse=True):
        updated = re.sub(rf"(?<![\w.]){re.escape(old)}(?=\.|\b)", moves[old], updated)

    if updated == source:
        return False
    print(f"[UPDATE] {path}")
    if not dry_run:
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(updated)
    return True


def python_files(root: Path):
    for path in root.rglob("*.py"):
        if not any(part in EXCLUDED for part in path.parts):
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("scripts"), help="Python source tree to scan")
    parser.add_argument("--move", action="append", default=[], metavar="OLD=NEW", help="Dotted module path mapping")
    parser.add_argument("--dry-run", action="store_true", help="Report changed files without writing them")
    args = parser.parse_args()
    try:
        moves = parse_moves(args.move)
    except ValueError as error:
        parser.error(str(error))
    if not args.root.is_dir():
        parser.error(f"Source root does not exist: {args.root}")

    changed = sum(rewrite_file(path, moves, dry_run=args.dry_run) for path in python_files(args.root))
    action = "would update" if args.dry_run else "updated"
    print(f"[OK] {action} {changed} Python files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
