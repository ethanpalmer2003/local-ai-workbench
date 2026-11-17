"""Rename a tracked file or folder and repoint every reference in the same change.

Run from C:/AI:
  python -m scripts.tools.rename_path --move notes/OLD.md=notes/NEW.md
  python -m scripts.tools.rename_path --move scripts/config/old=scripts/config/new --dry-run

The move is `git mv`, so history follows the path. References are the basenames, repo-relative
paths, dotted module names and `from package import module` imports that appear in Markdown,
Python, batch, YAML and JSON sources. Afterwards the docs and layout checks fail on any link or
rule the rewrite missed, so a move ends with `python -m scripts.review`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from scripts.tools.rewrite_imports import EXCLUDED

# - the workspace trees this repository does not own, so a source path is never a reference from there
PRUNE = EXCLUDED | {"data", "frameworks", "trash"}
TEXT_SUFFIXES = {".md", ".py", ".bat", ".yaml", ".yml", ".json", ".js", ".cjs", ".mjs"}
# - `from package import module` names the module by its last component, so it needs its own rewrite
FROM_IMPORT = re.compile(r"^(?P<head>\s*from\s+(?P<package>[\w.]+)\s+import\s+)(?P<names>[^\n]+)$", re.MULTILINE)
ROOT = Path(__file__).resolve().parents[2]


def parse_moves(values: list[str]) -> dict[str, str]:
    """Repo-relative OLD=NEW pairs, refusing anything that escapes the workspace."""
    moves: dict[str, str] = {}
    for value in values:
        old, separator, new = value.partition("=")
        if not separator or not old or not new:
            raise ValueError(f"Expected OLD_PATH=NEW_PATH, got {value!r}")
        for candidate in (old, new):
            path = PurePosixPath(candidate.replace("\\", "/"))
            # - a drive letter is absolute on Windows even though PurePosixPath does not say so
            if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", candidate):
                raise ValueError(f"Paths must stay inside the workspace: {candidate!r}")
        if old in moves and moves[old] != new:
            raise ValueError(f"Conflicting mappings for {old!r}")
        moves[old.replace("\\", "/")] = new.replace("\\", "/")
    if not moves:
        raise ValueError("Provide at least one --move OLD_PATH=NEW_PATH")
    return moves


def reference_forms(old: str, new: str) -> list[tuple[str, str]]:
    """Every spelling a reference can take, longest first so a path wins over a basename."""
    pairs: list[tuple[str, str]] = []
    if "/" in old:
        pairs.append((old, new))
        pairs.append((old.replace("/", "\\"), new.replace("/", "\\")))
    old_name, new_name = PurePosixPath(old).name, PurePosixPath(new).name
    if old_name != new_name and PurePosixPath(old).suffix:
        pairs.append((old_name, new_name))
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def dotted_forms(old: str, new: str) -> list[tuple[str, str]]:
    """A moved Python module is also imported by its dotted name, which a path rewrite never sees.

    A package `__init__.py` keeps the package name, so it has no dotted form of its own.
    """
    old_path, new_path = PurePosixPath(old), PurePosixPath(new)
    if old_path.suffix != ".py" or new_path.suffix != ".py":
        return []
    if old_path.name == "__init__.py" or len(old_path.parts) < 2:
        return []
    return [(".".join(old_path.with_suffix("").parts), ".".join(new_path.with_suffix("").parts))]


def import_name_forms(old: str, new: str) -> list[tuple[str, str, str]]:
    """`from package import module` names the module by its last component, so that needs the package."""
    old_path, new_path = PurePosixPath(old), PurePosixPath(new)
    if old_path.suffix != ".py" or new_path.suffix != ".py" or old_path.name == "__init__.py":
        return []
    if old_path.stem == new_path.stem or len(old_path.parts) < 2:
        return []
    return [(".".join(old_path.parent.parts), old_path.stem, new_path.stem)]


def rename_import_names(text: str, forms: list[tuple[str, str, str]]) -> str:
    """Rewrite the module component of a `from package import module` line and keep any alias."""
    if not forms:
        return text

    def replace(match: re.Match[str]) -> str:
        package = match.group("package")
        for expected, old, new in forms:
            if package != expected:
                continue
            names = []
            for name in match.group("names").split(","):
                word, _, alias = name.strip().partition(" as ")
                if word == old:
                    names.append(f"{new} as {alias.strip()}" if alias else new)
                else:
                    names.append(name.strip())
            return match.group("head") + ", ".join(names)
        return match.group(0)

    return FROM_IMPORT.sub(replace, text)


def rename_dotted(text: str, pairs: list[tuple[str, str]]) -> str:
    """Replace dotted names only at a word boundary, so a longer module sharing the prefix survives."""
    for old, new in pairs:
        text = re.sub(rf"{re.escape(old)}(?![\w])", lambda _match, replacement=new: replacement, text)
    return text


def move_paths(moves: dict[str, str], *, dry_run: bool, root: Path = ROOT) -> None:
    for old, new in moves.items():
        if not (root / old).exists():
            raise FileNotFoundError(f"Nothing to move at {old}")
        if (root / new).exists():
            raise FileExistsError(f"Target already exists: {new}")
        print(f"[MOVE] {old} -> {new}")
        if dry_run:
            continue
        (root / new).parent.mkdir(parents=True, exist_ok=True)
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", old], cwd=root, capture_output=True, text=True, check=False
        )
        if tracked.returncode == 0:
            subprocess.run(["git", "mv", old, new], cwd=root, check=True)
        else:
            (root / old).rename(root / new)


def text_files(root: Path) -> Iterable[Path]:
    """Prune the excluded trees while walking; a workspace walk through 700k files takes minutes."""
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = [name for name in subfolders if name not in PRUNE]
        for name in files:
            path = Path(folder) / name
            if path.suffix in TEXT_SUFFIXES:
                yield path


def rewrite_references(moves: dict[str, str], *, dry_run: bool, root: Path = ROOT) -> list[Path]:
    pairs = [pair for old, new in moves.items() for pair in reference_forms(old, new)]
    dotted = [pair for old, new in moves.items() for pair in dotted_forms(old, new)]
    imports = [form for old, new in moves.items() for form in import_name_forms(old, new)]
    changed = []
    # - the scan size is printed because a wrong root or an unpruned tree is the way this tool goes slow
    scanned = list(text_files(root))
    print(f"[SCAN] {len(scanned)} text file(s) under {root}")
    for path in scanned:
        text = path.read_text(encoding="utf-8", errors="replace")
        updated = text
        for old, new in pairs:
            updated = updated.replace(old, new)
        updated = rename_dotted(updated, dotted)
        updated = rename_import_names(updated, imports)
        if updated == text:
            continue
        print(f"[UPDATE] {path.relative_to(root).as_posix()}")
        changed.append(path)
        if not dry_run:
            path.write_text(updated, encoding="utf-8", newline="\n")
    return changed


def leftovers(moves: dict[str, str], *, root: Path = ROOT) -> list[str]:
    """References that survived the rewrite, which a manual review then has to explain."""
    forms = [
        pair for move, target in moves.items() for pair in (*reference_forms(move, target), *dotted_forms(move, target))
    ]
    names = [old for old, _ in forms]
    found = []
    for path in text_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        found.extend(f"{path.relative_to(root).as_posix()}: {name}" for name in names if name in text)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--move", action="append", default=[], metavar="OLD=NEW", help="Repo-relative path mapping")
    parser.add_argument("--dry-run", action="store_true", help="Report the move and the files without writing")
    args = parser.parse_args()
    try:
        moves = parse_moves(args.move)
    except ValueError as error:
        parser.error(str(error))

    move_paths(moves, dry_run=args.dry_run)
    changed = rewrite_references(moves, dry_run=args.dry_run)
    action = "would update" if args.dry_run else "updated"
    print(f"[OK] {action} {len(changed)} file(s); run `python -m scripts.review` for the link checks")
    remaining = leftovers(moves)
    for line in remaining:
        print(f"[WARN] Reference outside the rewrite: {line}")
    return int(bool(remaining))


if __name__ == "__main__":
    sys.exit(main())
