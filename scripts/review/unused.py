"""Dead code: a module-level function, class or constant that nothing in the sources names.

A name is dead when the Python sources mention it exactly as often as it is defined there. Scanning
the whole source text, strings and comments included, keeps the check cheap and keeps it honest:
a caller that reaches the name through `getattr`, a patch target or a doc-anchored reference counts.

Local unused variables and imports are not this check's job: ruff owns them as F841 and F401.
"""

import ast
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.sources import maintained_files

# - retired code awaiting a removal decision; the entry in notes/TODO.md owns that decision
RETIRED = {"scripts/launchers/audiocpp/tts_legacy_buffered.py"}


@dataclass(frozen=True)
class Definition:
    path: Path
    line: int
    kind: str
    name: str


def _skipped(path: Path) -> bool:
    """Tests are consumers, never definition owners; retired files await a removal decision."""
    try:
        relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    except ValueError:
        return path.name in {Path(item).name for item in RETIRED}
    return relative.startswith("scripts/tests/") or relative in RETIRED


def _module_definitions(path: Path, text: str) -> list[Definition]:
    """Functions, classes and constants a module exposes; nested names belong to their parent."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(Definition(path, node.lineno, "function", node.name))
        elif isinstance(node, ast.ClassDef):
            found.append(Definition(path, node.lineno, "class", node.name))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found.append(Definition(path, node.lineno, "constant", node.targets[0].id))
    return [item for item in found if not item.name.startswith("__")]


def dead_definitions(files: list[Path]) -> list[Definition]:
    sources = [path for path in files if path.suffix == ".py"]
    texts = {path: path.read_text(encoding="utf-8", errors="ignore") for path in sources}
    mentions: Counter[str] = Counter()
    for text in texts.values():
        mentions.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    dead = []
    for path, text in texts.items():
        if _skipped(path):
            continue
        for definition in _module_definitions(path, text):
            if mentions[definition.name] <= 1:
                dead.append(definition)
    return dead


def unreachable(files: list[Path]) -> list[str]:
    """Blocks that no path reaches; ruff has no rule for this, vulture does."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "vulture",
            *(str(path) for path in files if path.suffix == ".py"),
            "--min-confidence",
            "100",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if "unreachable code" in line]


def main(argv: list[str] | None = None) -> int:
    _ = argv
    files = maintained_files()
    dead = dead_definitions(files)
    unreachable_blocks = unreachable(files)
    if not dead:
        print(f"[OK] Dead code: {len([p for p in files if p.suffix == '.py'])} files, nothing unreferenced")
        return 0
    for item in dead[:MAX_REPORTED]:
        print(f"[FAIL] {item.path.name}:{item.line}: {item.kind} {item.name} is never referenced")
    for block in unreachable_blocks[:MAX_REPORTED]:
        print(f"[FAIL] {block}")
    total = len(dead) + len(unreachable_blocks)
    print(f"[FAIL] Dead code: {len(dead)} unreferenced definition(s), {len(unreachable_blocks)} unreachable block(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
