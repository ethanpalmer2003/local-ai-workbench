"""One bundle a heavier model reads instead of the whole repository.

The gate already settles what a light model can fix itself: formatting, lint, spelling, duplicate blocks and
folder caps all fail there, so this bundle carries only what needs judgment: the shape of the tree, the
rules that decide quality, and the exact places where no check looks. A reader starts at `HANDOFF.md`, opens
the ranked files in full, and answers the questions the bundle names; nothing else in the repository is
needed to judge those files.

The measurements here are prompts, never findings: a silent `except` may be deliberate, and a long function
may be one switch. They exist so a reader spends its time on the few places that deserve it.
"""

import argparse
import ast
import json
import time
from pathlib import Path
from typing import TypedDict

from scripts.config import project_config as project_cfg
from scripts.review.checks.inventory_code import maintained_python

# - a function past this many lines carries more than one idea, which a reader has to judge rather than fix
LONG_FUNCTION = 60
# - "too many entry points" is a shape question, not a count: a module past this needs a second look
WIDE_SURFACE = 12
SILENT = (ast.Pass, ast.Continue, ast.Return)
BUNDLE_NAME = "HANDOFF.md"


class FunctionRecord(TypedDict):
    """One public module-level function, with the shape a reader needs to judge it."""

    name: str
    line: int
    span: int
    signature: str
    documented: bool


class FileRecord(TypedDict):
    """One module: its call shapes and the places where no check looks."""

    path: str
    lines: int
    functions: list[FunctionRecord]
    classes: list[str]
    silent_excepts: list[int]
    broad_excepts: list[int]
    undocumented: list[int]


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The call shape a reader needs, without the body: arguments, return annotation and span."""
    arguments = [ast.unparse(argument) for argument in node.args.args]
    returns = ast.unparse(node.returns) if node.returns else "-"
    return f"({', '.join(arguments)}) -> {returns}"


def silent_except(node: ast.ExceptHandler) -> bool:
    """Whether a handler does nothing at all, which is where a real failure disappears."""
    if len(node.body) != 1:
        return False
    statement = node.body[0]
    if isinstance(statement, ast.Return):
        if statement.value is None:
            return True
        # - identity, not equality: `0 == False` would make a real return value look like a swallow
        return isinstance(statement.value, ast.Constant) and (
            statement.value.value is None or statement.value.value is False or statement.value.value == ""
        )
    return isinstance(statement, SILENT)


def broad_except(node: ast.ExceptHandler) -> bool:
    """Whether a handler catches everything, bare or as `Exception`, rather than what it expects."""
    kind = node.type
    if kind is None:
        return True
    return isinstance(kind, ast.Name) and kind.id in {"Exception", "BaseException"}


def file_record(path: Path, workspace: Path) -> FileRecord:
    """Everything the bundle says about one module, from a single parse."""
    source = path.read_text(encoding="utf-8-sig", errors="replace")
    tree = ast.parse(source)
    functions: list[FunctionRecord] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name.startswith("_"):
            continue
        functions.append(
            {
                "name": node.name,
                "line": node.lineno,
                "span": (node.end_lineno or node.lineno) - node.lineno + 1,
                "signature": signature(node),
                "documented": bool(ast.get_docstring(node)),
            }
        )
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    return {
        "path": path.relative_to(workspace).as_posix(),
        "lines": len(source.splitlines()),
        "functions": functions,
        "classes": [node.name for node in tree.body if isinstance(node, ast.ClassDef)],
        "silent_excepts": [node.lineno for node in handlers if silent_except(node)],
        "broad_excepts": [node.lineno for node in handlers if broad_except(node)],
        "undocumented": [item["line"] for item in functions if not item["documented"]],
    }


def weight(record: FileRecord) -> int:
    """How much a file asks of a reader: a silent handler and a long function cost the most."""
    long_functions = sum(1 for item in record["functions"] if int(item["span"]) > LONG_FUNCTION)
    return (
        3 * len(record["silent_excepts"])
        + len(record["broad_excepts"])
        + 2 * long_functions
        + (1 if len(record["functions"]) > WIDE_SURFACE else 0)
    )


def index(workspace: Path) -> list[FileRecord]:
    """One record per maintained Python file, heaviest first."""
    records = []
    for path in maintained_python(workspace / "scripts"):
        try:
            records.append(file_record(path, workspace))
        except (OSError, SyntaxError):
            continue
    return sorted(records, key=lambda record: (-weight(record), -int(record["lines"])))


def brief(records: list[FileRecord], ranked: int = 12) -> list[str]:
    """The markdown a heavier model reads first, and the only thing it needs before opening files."""
    total_functions = sum(len(record["functions"]) for record in records)
    silent = sum(len(record["silent_excepts"]) for record in records)
    broad = sum(len(record["broad_excepts"]) for record in records)
    wide = sum(1 for record in records if len(record["functions"]) > WIDE_SURFACE)
    lines = [
        "# Handoff brief",
        "",
        "Read this, then the files under **Where to look first**. The rest of the repository does not have to",
        "be read to judge them: the mechanical findings are already the gate's job, and this bundle omits them.",
        "",
        "## What this is",
        "",
        "A Windows-only workspace that drives local models: launchers, catalog updaters, benchmarks, a test",
        "suite and the review gate that guards them. Rules live in `.agents/CODE.md`; the gate's sections and",
        "their levels in `.agents/CHECKS.md`. A change lands through `python -m scripts.review` and",
        "`python -m scripts.tests.run`, both scoped to the change and both taking `--all`.",
        "",
        "## The rules that decide quality",
        "",
        "- One owner per fact: a literal, a rule or a path is spelled once, and every other mention imports it.",
        "- A name states its object: `selection`, not `scoping`; a folder that holds one thing names it.",
        "- No unnecessary logic: the presence of something (a field, a file, a flag) carries the decision.",
        "- Smaller pieces with clear branches beat clever economy; a helper nothing exercises is complexity.",
        "- A failure is raised and named, never swallowed: a silent `except` is the smell this bundle ranks.",
        "- A dependency is preferred to a hand-written traversal; the standard library is checked first.",
        "",
        "## The shape",
        "",
        f"- {len(records)} maintained Python files, {total_functions} public module-level functions.",
        f"- {silent} silent handler(s) and {broad} broad handler(s) across the tree.",
        f"- {wide} module(s) expose more than {WIDE_SURFACE} public functions.",
        "",
        "## What a cheap check already settles",
        "",
        "Formatting, lint, spelling, ASCII punctuation, duplicate blocks, line length, folder caps, file length",
        "caps, dead code and type errors all fail the gate. Do not spend judgment on them; if one is wrong, it",
        "is a gate defect and worth saying so once.",
        "",
        "## Where to look first",
        "",
        "Ranked by how much judgment a file asks for, not by how long it is.",
        "",
        "| File | Lines | Public functions | Silent handlers | Broad handlers | Long functions |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for record in records[:ranked]:
        long_functions = sum(1 for item in record["functions"] if int(item["span"]) > LONG_FUNCTION)
        lines.append(
            f"| {record['path']} | {record['lines']} | {len(record['functions'])} | "
            f"{len(record['silent_excepts'])} | {len(record['broad_excepts'])} | {long_functions} |"
        )
    lines.extend(
        (
            "",
            "## The questions this bundle was built for",
            "",
            "1. Is any abstraction in those files the wrong one: a wrapper that only forwards, a class whose",
            "   state belongs to its caller, a module that owns two unrelated jobs?",
            "2. Is a silent handler hiding a real failure that should raise, or is it deliberate and worth a",
            "   one-line comment saying why?",
            "3. Does a function past its length limit carry two ideas that a reader cannot follow in one pass?",
            "4. Is any rule from `.agents/CODE.md` re-implemented in a second place, so the two can drift?",
            "",
            "Answer per file with the line numbers, say which findings are real and which are deliberate, and",
            "leave mechanical fixes out: the light model applies those.",
            "",
            "`ast_map.json` beside this file holds every file's public functions, signatures and span, for a",
            "reader that wants the shape without opening a single file.",
        )
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranked", type=int, default=12, help="how many files the brief names first")
    parser.add_argument("--out", help="folder for the bundle (default: the generated handoff tree)")
    args = parser.parse_args(argv)
    records = index(project_cfg.BASE_DIR)
    destination = (
        Path(args.out) if args.out else project_cfg.component("shared").generated_dir / "handoff" / str(time.time_ns())
    )
    destination.mkdir(parents=True, exist_ok=False)
    (destination / BUNDLE_NAME).write_text("\n".join(brief(records, args.ranked)) + "\n", encoding="utf-8")
    (destination / "ast_map.json").write_text(json.dumps({"files": records}, indent=2) + "\n", encoding="utf-8")
    silent = sum(len(record["silent_excepts"]) for record in records)
    print(f"[OK] Handoff: {len(records)} files, {silent} silent handler(s)")
    print(f"[OK] Bundle: {destination / BUNDLE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
