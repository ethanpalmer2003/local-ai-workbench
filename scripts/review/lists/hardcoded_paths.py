"""Paths that a config module owns must not be spelled by hand somewhere else.

`project_config` owns where runtime data lives, and every reader imports it. A literal copy of a
config-owned path is how the same move had to be repeated across five files: the write stayed correct
until the owner changed, then silently kept writing the old place. The check reads joined path literals
(`root / "scripts" / "state"`) as well as hyphen-free strings, so both spellings fail.
"""

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.file_sets import maintained_files

# - config-owned trees, by the repo-relative name each one is allowed to be spelled under
OWNED_ROOTS = ("state", "runs", "data", "frameworks", "trash", "graphify-out")
# - literal text that names a config-owned tree below `scripts/`, which is the old layout
STALE = re.compile(r"scripts[/\\](?:state|tests[/\\]output|benchmarks[/\\]output)\b")
# - a file that may name the paths: the owner itself, and this check's own fixtures
OWNERS = frozenset({"scripts/config/project_config.py", "scripts/review/lists/hardcoded_paths.py"})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    detail: str


def _relative(path: Path) -> str:
    try:
        return path.relative_to(project_cfg.BASE_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def joined_path_literals(tree: ast.AST) -> list[tuple[str, int]]:
    """Every `/`-joined chain of string literals, as a path and its line."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        parts: list[str] = []
        line = getattr(node, "lineno", 0)
        pending = node
        while isinstance(pending, ast.BinOp) and isinstance(pending.op, ast.Div):
            right = pending.right
            if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
                parts = []
                break
            parts.insert(0, right.value)
            pending = pending.left
        if isinstance(pending, ast.Constant) and isinstance(pending.value, str):
            parts.insert(0, pending.value)
        if len(parts) >= 2:
            found.append(("/".join(parts), line))
    return found


def _stale_lines(relative: str, text: str) -> tuple[list[Finding], set[int]]:
    """Lines naming a path that moved under a config owner, plus their numbers."""
    found = [
        Finding(relative, number, "names a path that moved under a config owner")
        for number, line in enumerate(text.splitlines(), start=1)
        if STALE.search(line)
    ]
    return found, {item.line for item in found}


def _joined_lines(relative: str, tree: ast.AST, reported: set[int]) -> list[Finding]:
    """Joined literals that spell a config-owned tree below `scripts/`, one finding per line."""
    found = []
    seen = set(reported)
    for joined, line in joined_path_literals(tree):
        if line in seen:
            continue
        segments = joined.split("/")
        if len(segments) >= 2 and segments[0] == "scripts" and segments[1] in OWNED_ROOTS:
            found.append(Finding(relative, line, f"spells {joined!r}; import the owning constant"))
            seen.add(line)
    return found


def findings(paths: list[Path] | None = None) -> list[Finding]:
    """Every hand-spelled config-owned path outside its owner."""
    checked: list[Finding] = []
    for path in maintained_files() if paths is None else paths:
        if path.suffix.lower() not in {".py", ".toml", ".yml", ".yaml", ".bat", ".json"}:
            continue
        relative = _relative(path)
        if relative in OWNERS or path.name in {"project_config.py", "hardcoded_paths.py"}:
            continue
        if relative.startswith("scripts/tests/cases/"):
            # - a test spells the path to assert what the owner returns; that is not a second copy
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        stale, reported = _stale_lines(relative, text)
        checked.extend(stale)
        if path.suffix.lower() == ".py":
            try:
                checked.extend(_joined_lines(relative, ast.parse(text), reported))
            except SyntaxError:
                continue
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.parse_args(argv)
    problems = findings()
    for finding in problems:
        print(f"[FAIL] {finding.path}:{finding.line}: {finding.detail}")
    if problems:
        print("[NEXT] read the path from project_config instead of spelling it")
        return 1
    print("[OK] no hand-spelled config-owned path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
