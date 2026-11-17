"""Rename a tracked file or folder and repoint every reference in the same change.

Run from C:/AI:
  python -m scripts.tools.rename_path --move notes/OLD.md=notes/NEW.md
  python -m scripts.tools.rename_path --move notes/OLD.md=notes/NEW.md --apply

The move is `git mv`, so history follows the path. References are the basenames, repo-relative
paths, dotted module names and `from package import module` imports that appear in Markdown,
Python, batch, YAML and JSON sources. The tool always previews the count and the files first: a
rename rewrites many files, and a count read after the fact is too late to stop one that went wide.
Writing needs `--apply` and the consent flag, so an unattended run cannot move anything by accident.
Afterwards the docs and layout checks fail on any link or rule the rewrite missed, so a move ends
with `python -m scripts.review`.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from scripts.shared import consent
from scripts.tools.rewrite_imports import EXCLUDED

# - the workspace and generated trees this repository does not own, so a source path is never a reference there
PRUNE = EXCLUDED | {"data", "frameworks", "trash", "graphify-out"}
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
    return moves


def reference_forms(old: str, new: str, *, bare: bool = True) -> list[tuple[str, str]]:
    """Every spelling a reference can take, longest first so a path wins over a basename.

    The bare basename is only a reference when the tree holds one file by that name: rewriting
    every `README.md` because one of forty moved is how a rename corrupts a repository.
    """
    pairs: list[tuple[str, str]] = []
    if "/" in old:
        pairs.append((old, new))
        pairs.append((old.replace("/", "\\"), new.replace("/", "\\")))
    old_name, new_name = PurePosixPath(old).name, PurePosixPath(new).name
    if bare and old_name != new_name and PurePosixPath(old).suffix:
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


def rename_collapsed_imports(text: str, forms: list[tuple[str, str, str, str]]) -> str:
    """`from old.package import module` becomes `from new.parent import renamed`, because the package is gone."""
    if not forms:
        return text

    def replace(match: re.Match[str]) -> str:
        for old_package, old_name, new_package, new_name in forms:
            if match.group("package") != old_package:
                continue
            names = []
            changed = False
            for name in match.group("names").split(","):
                word, _, alias = name.strip().partition(" as ")
                if word != old_name:
                    names.append(name.strip())
                    continue
                # - code that calls `old_name.thing()` keeps working, so the binding name is preserved
                bound = alias.strip() if alias else old_name if new_name != old_name else ""
                names.append(f"{new_name} as {bound}" if bound else new_name)
                changed = True
            if not changed:
                return match.group(0)
            head = match.group("head")
            indent = head[: len(head) - len(head.lstrip())]
            return f"{indent}from {new_package} import {', '.join(names)}"
        return match.group(0)

    return FROM_IMPORT.sub(replace, text)


def rewrite_text(
    text: str,
    pairs: list[tuple[str, str]],
    dotted: list[tuple[str, str]],
    imports: list[tuple[str, str, str]],
    collapsed: list[tuple[str, str, str, str]] | None = None,
    local: list[tuple[str, str]] | None = None,
) -> tuple[str, int]:
    """Apply every reference form to one file's text, and count the references that changed.

    `local` holds the bare basenames of the moved files, which only mean something in a file that
    sits in the moved file's own directory; a name like `README.md` matched elsewhere is a different file.
    """
    updated = text
    changes = 0
    for old, new in pairs:
        changes += updated.count(old)
        updated = updated.replace(old, new)
    for old, new in local or []:
        pattern = rf"(?<![\w]){re.escape(old)}(?![\w])"
        changes += len(re.findall(pattern, updated))
        updated = re.sub(pattern, lambda _match, replacement=new: replacement, updated)
    for old, _new in dotted:
        changes += len(re.findall(rf"{re.escape(old)}(?![\w])", updated))
    for old_package, old_name, _package, _name in collapsed or []:
        pattern = rf"^\s*from\s+{re.escape(old_package)}\s+import\s+[^\n]*\b{re.escape(old_name)}\b"
        changes += len(re.findall(pattern, updated, re.MULTILINE))
    updated = rename_dotted(updated, dotted)
    updated = rename_import_names(updated, imports)
    updated = rename_collapsed_imports(updated, collapsed or [])
    return updated, changes


def _moved_forms(moves: dict[str, str]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """The dotted and import-name forms, which do not depend on where the move happens."""
    dotted = [pair for old, new in moves.items() for pair in dotted_forms(old, new)]
    imports = [form for old, new in moves.items() for form in import_name_forms(old, new)]
    return dotted, imports


def _pairs(moves: dict[str, str], root: Path = ROOT) -> tuple[list[tuple[str, str]], dict[Path, list[tuple[str, str]]]]:
    """Path pairs, and the bare basenames each move may repoint inside its own directory only."""
    pairs = [pair for move, target in moves.items() for pair in reference_forms(move, target, bare=False)]
    local: dict[Path, list[tuple[str, str]]] = {}
    for move, target in moves.items():
        old_name, new_name = PurePosixPath(move).name, PurePosixPath(target).name
        if old_name != new_name:
            directory = root / PurePosixPath(move).parent
            local.setdefault(directory, []).append((old_name, new_name))
    return pairs, local


def plan_forms(
    pairs: list[tuple[str, str]],
    dotted: list[tuple[str, str]],
    imports: list[tuple[str, str, str]],
    *,
    root: Path = ROOT,
    collapsed: list[tuple[str, str, str, str]] | None = None,
    local: dict[Path, list[tuple[str, str]]] | None = None,
) -> list[tuple[Path, int]]:
    """Every file a rewrite would touch and how many references each holds, without writing."""
    local = local or {}
    planned = []
    for path in text_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        updated, changes = rewrite_text(text, pairs, dotted, imports, collapsed, local.get(path.parent))
        if updated != text:
            planned.append((path, changes))
    return planned


def preview(moves: dict[str, str], *, root: Path = ROOT) -> list[tuple[Path, int]]:
    """Every file the rewrite would touch and how many references each holds, without writing."""
    pairs, local = _pairs(moves, root)
    dotted, imports = _moved_forms(moves)
    return plan_forms(pairs, dotted, imports, root=root, local=local)


def rewrite_forms(
    pairs: list[tuple[str, str]],
    dotted: list[tuple[str, str]],
    imports: list[tuple[str, str, str]],
    *,
    dry_run: bool,
    root: Path = ROOT,
    collapsed: list[tuple[str, str, str, str]] | None = None,
    local: dict[Path, list[tuple[str, str]]] | None = None,
) -> list[Path]:
    """Apply one set of reference forms to every source file, writing only when asked."""
    local = local or {}
    changed = []
    for path in text_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        updated, changes = rewrite_text(text, pairs, dotted, imports, collapsed, local.get(path.parent))
        if updated == text:
            continue
        print(f"[UPDATE] {path.relative_to(root).as_posix()} ({changes} reference(s))")
        changed.append(path)
        if not dry_run:
            path.write_text(updated, encoding="utf-8", newline="\n")
    return changed


def rewrite_references(moves: dict[str, str], *, dry_run: bool, root: Path = ROOT) -> list[Path]:
    pairs, local = _pairs(moves, root)
    dotted, imports = _moved_forms(moves)
    return rewrite_forms(pairs, dotted, imports, dry_run=dry_run, root=root, local=local)


class Collapse(NamedTuple):
    """A one-module package, the module it holds, and the forms that fold it into `target`."""

    package: Path
    module: Path
    init: Path
    pairs: list[tuple[str, str]]
    dotted: list[tuple[str, str]]
    imports: list[tuple[str, str, str, str]]


def collapse_plan(package: str, target: str, *, root: Path = ROOT) -> Collapse:
    """Validate that `package` holds one module and one docstring `__init__`, then plan the fold."""
    directory = root / package
    init = directory / "__init__.py"
    modules = [path for path in directory.glob("*.py") if path.name != "__init__.py"] if directory.is_dir() else []
    if not init.is_file() or len(modules) != 1:
        raise ValueError(f"Not a package holding one module: {package}")
    if any(child.is_dir() and child.name not in PRUNE for child in directory.iterdir()):
        raise ValueError(f"Package holds a subdirectory, so it is not one module: {package}")
    body = ast.parse(init.read_text(encoding="utf-8")).body
    if body and not (len(body) == 1 and isinstance(body[0], ast.Expr)):
        raise ValueError(f"__init__.py holds code; merge it into the module by hand: {package}")
    module = modules[0]
    old = module.relative_to(root).as_posix()
    moves = {old: target}
    pairs, _local = _pairs(moves, root)
    return Collapse(
        package=directory,
        module=module,
        init=init,
        pairs=pairs,
        dotted=dotted_forms(old, target),
        # - the package disappears, so its one module is imported from the parent under the new name
        imports=[
            (
                ".".join(PurePosixPath(package).parts),
                module.stem,
                ".".join(PurePosixPath(target).parent.parts),
                PurePosixPath(target).stem,
            )
        ],
    )


def collapse(package: str, target: str, *, dry_run: bool, root: Path = ROOT) -> list[Path]:
    """Fold a one-module package into `target` and repoint every reference to it."""
    plan = collapse_plan(package, target, root=root)
    if not dry_run:
        module = plan.module.relative_to(root).as_posix()
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", module], cwd=root, capture_output=True, text=True, check=False
        )
        if tracked.returncode == 0:
            subprocess.run(["git", "mv", module, target], cwd=root, check=True)
            subprocess.run(["git", "rm", "-q", plan.init.relative_to(root).as_posix()], cwd=root, check=True)
        else:
            plan.module.rename(root / target)
            plan.init.unlink()
        # - only the excluded caches can remain, since the package held one module and nothing else
        shutil.rmtree(plan.package, ignore_errors=True)
    return rewrite_forms(plan.pairs, plan.dotted, [], dry_run=dry_run, root=root, collapsed=plan.imports)


def leftovers(moves: dict[str, str], *, root: Path = ROOT) -> list[str]:
    """References that survived the rewrite, which a manual review then has to explain."""
    scanned = list(text_files(root))
    forms = [
        pair for move, target in moves.items() for pair in (*reference_forms(move, target), *dotted_forms(move, target))
    ]
    names = [old for old, _ in forms]
    found = []
    for path in scanned:
        text = path.read_text(encoding="utf-8", errors="replace")
        found.extend(f"{path.relative_to(root).as_posix()}: {name}" for name in names if name in text)
    return found


def parse_collapses(values: list[str]) -> list[tuple[str, str]]:
    """PACKAGE=MODULE.py pairs; the target names the module the collapsed package becomes."""
    collapses: list[tuple[str, str]] = []
    for value in values:
        package, separator, target = value.partition("=")
        if not separator or not package or not target.endswith(".py"):
            raise ValueError(f"Expected PACKAGE=MODULE.py, got {value!r}")
        collapses.append((package, target))
    return collapses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--move", action="append", default=[], metavar="OLD=NEW", help="Repo-relative path mapping")
    parser.add_argument(
        "--collapse",
        action="append",
        default=[],
        metavar="PACKAGE=MODULE.py",
        help="Fold a package holding one module into that module path, deleting its __init__.py",
    )
    parser.add_argument("--apply", action="store_true", help="Move the paths and rewrite; without it, preview only")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, which is the default; kept for habit")
    consent.flag(parser)
    args = parser.parse_args(argv)
    try:
        moves = parse_moves(args.move)
        collapses = parse_collapses(args.collapse)
    except ValueError as error:
        parser.error(str(error))
    if not moves and not collapses:
        parser.error("Provide at least one --move OLD_PATH=NEW_PATH or --collapse PACKAGE=MODULE.py")

    planned = preview(moves, root=ROOT)
    for package, target in collapses:
        try:
            plan = collapse_plan(package, target, root=ROOT)
        except ValueError as error:
            parser.error(str(error))
        planned += plan_forms(plan.pairs, plan.dotted, [], root=ROOT, collapsed=plan.imports)
    references = sum(count for _path, count in planned)
    print(f"[SCAN] {len(list(text_files(ROOT)))} text file(s) under {ROOT}")
    print(f"[PREVIEW] {references} reference(s) in {len(planned)} file(s)")
    for path, count in planned:
        print(f"[PREVIEW] {path.relative_to(ROOT).as_posix()} ({count} reference(s))")
    if not args.apply or args.dry_run:
        print(f"[NEXT] re-run with --apply and {consent.FLAG} to move and rewrite")
        return 0
    summary = f"Move {len(moves)} path(s), collapse {len(collapses)} package(s) and rewrite {len(planned)} file(s)"
    if not consent.confirm(summary, args.yes):
        return 1

    move_paths(moves, dry_run=False)
    for package, target in collapses:
        collapse(package, target, dry_run=False)
    changed = rewrite_references(moves, dry_run=False)
    print(f"[OK] moved {len(moves)} path(s), collapsed {len(collapses)}, updated {len(changed)} file(s)")
    remaining = leftovers(moves)
    for line in remaining:
        print(f"[WARN] Reference outside the rewrite: {line}")
    return int(bool(remaining))


if __name__ == "__main__":
    sys.exit(main())
