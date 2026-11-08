"""Review repository structure, source-file sizes, Python function complexity and duplicate bodies."""

import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg

MAX_DEPTH = 4
MAX_CODE_LINES = 100
MAX_SMALL_FOLDER_ITEMS = 3
MIN_DUPLICATE_LINES = 15
DEBT_DOC = project_cfg.SCRIPTS_DIR / "review" / "COMPLEXITY-DEBT.md"
DEBT_PREAMBLE = (
    "# McCabe debt",
    "",
    "Functions above the gate of 10. Each carries `# noqa: C901`; delete the annotation when the function is split.",
    "Regenerate with `python -m scripts.review.inventory_code --complexity-debt` rather than editing by hand.",
    "",
    "| Complexity | Function |",
    "| ---: | --- |",
)
EXCLUDED = {".git", ".venv", "state", "__pycache__", ".pytest_cache", ".ruff_cache"}
REVIEW_EXCLUDED = EXCLUDED | {
    "frameworks",
    "data",
    "trash",
    "output",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".mypy_cache",
    ".zed",
    "old",
    "retired",
}
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
INLINE_NOQA = re.compile(r"#\s*noqa\b", re.IGNORECASE)
BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)


@dataclass(frozen=True)
class FunctionSize:
    path: str
    name: str
    line: int
    code_lines: int
    depth: int

    @property
    def exceeds_limits(self) -> bool:
        return self.code_lines > MAX_CODE_LINES or self.depth > MAX_DEPTH


@dataclass(frozen=True)
class Fingerprint:
    path: str
    name: str
    line: int
    code_lines: int
    digest: str


def nesting(node: ast.AST, depth: int = 0) -> int:
    if isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
        return depth
    current = depth + int(isinstance(node, BLOCKS))
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        current += len(node.generators)
    result = current
    for field, value in ast.iter_fields(node):
        children = value if isinstance(value, list) else [value]
        for child in children:
            if not isinstance(child, ast.AST):
                continue
            # - An elif is an alternative at the same level, not a nested if.
            is_elif = (
                isinstance(node, ast.If)
                and field == "orelse"
                and isinstance(child, ast.If)
                and child.col_offset == node.col_offset
            )
            base = depth if is_elif else current
            result = max(result, nesting(child, base))
    return result


def code_line_numbers(source: str, tree: ast.Module) -> set[int]:
    ignored = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, *FUNCTIONS, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        first = body[0] if isinstance(body, list) and body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            ignored.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENDMARKER,
            tokenize.ENCODING,
        ):
            continue
        lines.update(range(token.start[0], token.end[0] + 1))
    return lines - ignored


def inspect_source(source: str, path: str) -> list[FunctionSize]:
    tree = ast.parse(source, filename=path)
    code_lines = code_line_numbers(source, tree)
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTIONS):
            continue
        own_lines = {line for line in code_lines if node.lineno <= line <= (node.end_lineno or node.lineno)}
        for child in ast.walk(node):
            if child is node or not isinstance(child, (*FUNCTIONS, ast.ClassDef)):
                continue
            for statement in child.body:
                own_lines.difference_update(range(statement.lineno, (statement.end_lineno or statement.lineno) + 1))
        count = len(own_lines)
        depth = max((nesting(child) for child in node.body), default=0)
        results.append(FunctionSize(path, node.name, node.lineno, count, depth))
    return results


def fingerprints_source(source: str, path: str) -> list[Fingerprint]:
    """Fingerprint every function body (name/docstring excluded) that clears the duplication threshold."""
    tree = ast.parse(source, filename=path)
    code_lines = code_line_numbers(source, tree)
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTIONS):
            continue
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        if not body:
            continue
        own = len({line for line in code_lines if node.lineno <= line <= (node.end_lineno or node.lineno)})
        if own < MIN_DUPLICATE_LINES:
            continue
        normal = "\n".join([ast.dump(node.args)] + [ast.dump(statement) for statement in body])
        digest = hashlib.sha256(normal.encode("utf-8")).hexdigest()
        results.append(Fingerprint(path, node.name, node.lineno, own, digest))
    return results


def duplicate_groups(fingerprints: list[Fingerprint]) -> list[list[Fingerprint]]:
    grouped: dict[str, list[Fingerprint]] = {}
    for item in fingerprints:
        grouped.setdefault(item.digest, []).append(item)
    groups = [sorted(items, key=lambda item: (item.path, item.line)) for items in grouped.values() if len(items) > 1]
    groups.sort(key=lambda items: (-items[0].code_lines, items[0].path, items[0].line))
    return groups


def maintained_python(root: Path):
    for directory, folders, files in os.walk(root):
        parent = Path(directory)
        folders[:] = [name for name in folders if name not in EXCLUDED and not (parent == root and name == "tests")]
        for name in sorted(files):
            if name.endswith(".py"):
                yield parent / name


def repository_inventory(root: Path) -> tuple[list[dict[str, int | str]], list[dict[str, int | str]]]:
    folders: list[dict[str, int | str]] = []
    source_files: list[dict[str, int | str]] = []
    for directory, children, names in os.walk(root):
        parent = Path(directory)
        children[:] = sorted(name for name in children if name not in REVIEW_EXCLUDED)
        visible_names = [name for name in names if name not in {"Thumbs.db", ".DS_Store"}]
        markdown_files = sum(Path(name).suffix.lower() == ".md" for name in visible_names)
        python_modules = sum(
            Path(name).suffix.lower() == ".py" and name.lower() != "__init__.py" for name in visible_names
        )
        folders.append(
            {
                "directory": "." if parent == root else parent.relative_to(root).as_posix(),
                "files": len(visible_names),
                "subdirectories": len(children),
                "items": len(visible_names) + len(children),
                "markdown_files": markdown_files,
                "python_modules": python_modules,
            }
        )
        for name in visible_names:
            path = parent / name
            if path.suffix.lower() not in {".py", ".md"}:
                continue
            try:
                line_count = len(path.read_text(encoding="utf-8-sig", errors="replace").splitlines())
            except OSError:
                continue
            source_files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "type": path.suffix.lower().lstrip("."),
                    "lines": line_count,
                }
            )
    folders.sort(key=lambda item: str(item["directory"]).casefold())
    source_files.sort(key=lambda item: (-int(item["lines"]), str(item["path"]).casefold()))
    return folders, source_files


def folder_inventory_report(
    folders: list[dict[str, int | str]],
    sparse_folders: list[dict[str, int | str]],
    small_folders: list[dict[str, int | str]],
) -> list[str]:
    lines = [
        "",
        "## Folder contents",
        "",
        "| Folder | Files | Subdirectories | Total items | .md files | Python modules* |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {item['directory']} | {item['files']} | {item['subdirectories']} | {item['items']} | "
        f"{item['markdown_files']} | {item['python_modules']} |"
        for item in folders
    )
    lines.extend(("", "*Python modules exclude `__init__.py`.", "", "## Empty or one-item folders", ""))
    lines.extend(f"- {item['directory']} ({item['items']} item(s))" for item in sparse_folders)
    if not sparse_folders:
        lines.append("None.")
    lines.extend(
        (
            "",
            f"## Small-folder merge candidates (2 to {MAX_SMALL_FOLDER_ITEMS} direct items)",
            "",
            "Review whether these groups have a distinct owner before merging; low counts alone are not a violation.",
            "",
            "| Folder | Items | .md files | Python modules* |",
            "| --- | ---: | ---: | ---: |",
        )
    )
    lines.extend(
        f"| {item['directory']} | {item['items']} | {item['markdown_files']} | {item['python_modules']} |"
        for item in small_folders
    )
    if not small_folders:
        lines.append("| None | - | - | - |")
    return lines


def _duplicate_section(duplicates: list[list[Fingerprint]]) -> list[str]:
    lines = [
        "",
        "## Duplicate function bodies",
        "",
        f"Identical normalized bodies at or above {MIN_DUPLICATE_LINES} code lines (advisory; not a pass/fail gate).",
        "",
        "| Copies | Code lines | Functions |",
        "| ---: | ---: | --- |",
    ]
    if not duplicates:
        return [*lines, "| None | - | - |"]
    lines.extend(
        f"| {len(group)} | {group[0].code_lines} | "
        + "; ".join(f"{item.path}:{item.line} {item.name}" for item in group)
        + " |"
        for group in duplicates
    )
    return lines


def _suppression_section(suppressions: list[str]) -> list[str]:
    lines = [
        "",
        "## Inline suppressions",
        "",
        "Every suppression belongs in `pyproject.toml`; an inline annotation fails the gate.",
        "",
    ]
    return [*lines, *(f"- {item}" for item in suppressions)] if suppressions else [*lines, "None."]


def _dependency_section(counts: dict[str, int]) -> list[str]:
    if not counts:
        return []
    return [
        "",
        "## Dependencies",
        "",
        f"{counts['locked']} locked; {counts['installed']} installed; "
        f"{counts['unused']} outside the import graph; {counts['drift']} lock issues.",
    ]


def report(
    results: list[FunctionSize],
    files: int,
    folders: list[dict[str, int | str]],
    source_files: list[dict[str, int | str]],
    artifacts: Path,
    duplicates: list[list[Fingerprint]],
    suppressions: list[str],
    dependencies: dict[str, int] | None = None,
) -> int:
    sparse_folders = [
        item
        for item in folders
        if int(item["items"]) <= 1 and not (str(item["directory"]).endswith("/patches") and int(item["files"]) == 1)
    ]
    small_folders = [item for item in folders if 1 < int(item["items"]) <= MAX_SMALL_FOLDER_ITEMS]
    violations = sorted(
        (item for item in results if item.exceeds_limits),
        key=lambda item: (-item.depth, -item.code_lines, item.path, item.line),
    )
    payload = {
        "limits": {"depth": MAX_DEPTH, "code_lines": MAX_CODE_LINES},
        "files": files,
        "functions": len(results),
        "violations": [asdict(item) for item in violations],
        "duplicate_limits": {"min_code_lines": MIN_DUPLICATE_LINES},
        "duplicate_groups": [[asdict(item) for item in group] for group in duplicates],
        "folders": folders,
        "sparse_folders": sparse_folders,
        "small_folder_candidates": small_folders,
        "source_file_lines": source_files,
        "inline_suppressions": suppressions,
        "dependencies": dependencies or {},
    }
    lines = [
        "# Repository code review",
        "",
        f"{len(folders)} folders; {len(source_files)} Python/Markdown files; {files} maintained Python files audited; "
        f"{len(results)} functions; {len(violations)} complexity violations; {len(duplicates)} duplicate groups.",
        "",
        f"Function limits: depth {MAX_DEPTH}, {MAX_CODE_LINES} code lines per function.",
        "Blank/comment/docstring lines excluded from function size; multiline signatures/data count. Nested bodies are",
        "measured independently. Function audit excludes the tests tree; benchmarks and probes are included. File/folder inventory excludes",
        "third-party installs, model data, generated state, trash and caches. Whole-file/folder sizes are context only;",
        "they have no pass/fail threshold. JavaScript/TypeScript line counts are not included.",
        "",
        "## Largest Python and Markdown files",
        "",
        "| File | Type | Lines |",
        "| --- | --- | ---: |",
    ]
    lines.extend(f"| {item['path']} | {item['type']} | {item['lines']} |" for item in source_files[:100])
    lines.extend(folder_inventory_report(folders, sparse_folders, small_folders))
    lines.extend(
        (
            "",
            "## Function complexity findings",
            "",
            "| File:line | Function | Code lines | Depth |",
            "| --- | --- | ---: | ---: |",
        )
    )
    lines.extend(f"| {item.path}:{item.line} | {item.name} | {item.code_lines} | {item.depth} |" for item in violations)
    lines.extend(_duplicate_section(duplicates))
    lines.extend(_suppression_section(suppressions))
    lines.extend(_dependency_section(dependencies or {}))
    (artifacts / "review.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (artifacts / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(folders)} folders, {len(source_files)} Python/Markdown files; {len(violations)} complexity violations")
    if suppressions:
        print(f"[FAIL] {len(suppressions)} inline suppression(s); move them into pyproject.toml")
        for item in suppressions[:10]:
            print(f"[FAIL] {item}")
    if sparse_folders:
        print(f"[WARN] {len(sparse_folders)} empty or one-item folders; see report.")
    if small_folders:
        print(
            f"[INFO] {len(small_folders)} folders have 2 to {MAX_SMALL_FOLDER_ITEMS} items; review candidates in report."
        )
    if duplicates:
        print(f"[INFO] {len(duplicates)} duplicate function groups (>= {MIN_DUPLICATE_LINES} code lines); see report.")
    print(f"Review report: {artifacts / 'review.md'}")
    return bool(violations or suppressions)


def _debt_row(item: dict[str, Any], root: Path) -> tuple[int, str, str]:
    match = re.search(r"`(.+)` is too complex \((\d+) >", str(item.get("message", "")))
    location = item.get("location") or {}
    path = Path(str(item.get("filename", ""))).relative_to(root).as_posix()
    if not match:
        return 0, f"{path}:{location.get('row', 0)}", "?"
    return int(match.group(2)), f"{path}:{location.get('row', 0)}", f"`{match.group(1)}`"


def complexity_debt(root: Path) -> int:
    """Rewrite the debt table from ruff's McCabe count with the grandfathering noqa ignored."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            "pyproject.toml",
            "--select",
            "C90",
            "--ignore-noqa",
            "--output-format",
            "json",
            ".",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    rows = sorted(
        (_debt_row(item, root) for item in json.loads(result.stdout or "[]") if item.get("code") == "C901"),
        key=lambda row: (-row[0], row[1]),
    )
    lines = [*DEBT_PREAMBLE, *(f"| {score} | `{path}` {name} |" for score, path, name in rows)]
    if not rows:
        lines.append("| None | - |")
    lines.extend(("", f"Remaining: {len(rows)}."))
    DEBT_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(rows)


def python_sources(root: Path):
    """Every maintained Python file, tests included; generated evidence and vendors excluded."""
    for directory, folders, names in os.walk(root):
        parent = Path(directory)
        folders[:] = sorted(name for name in folders if name not in REVIEW_EXCLUDED)
        for name in sorted(names):
            if name.endswith(".py"):
                yield parent / name


def _comment_lines(source: str):
    """(line number, comment text) for real comments; docstrings and string literals are prose, not suppressions."""
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                yield token.start[0], token.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return


def suppression_issues(root: Path) -> list[str]:
    """Inline `# noqa` is banned: every suppression belongs in pyproject's per-file ignores."""
    issues = []
    for path in python_sources(root):
        try:
            source = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for number, comment in _comment_lines(source):
            if INLINE_NOQA.search(comment):
                issues.append(f"Inline suppression: {path.relative_to(project_cfg.BASE_DIR).as_posix()}:{number}")
    return issues


def main(dependencies: dict[str, int] | None = None) -> int:
    if "--complexity-debt" in sys.argv[1:]:
        print(f"Complexity debt rows: {complexity_debt(project_cfg.BASE_DIR)} -> {DEBT_DOC.name}")
        return 0
    root = project_cfg.SCRIPTS_DIR
    files = list(maintained_python(root))
    results = [
        result
        for path in files
        for result in inspect_source(path.read_text(encoding="utf-8-sig"), path.relative_to(root).as_posix())
    ]
    fingerprints = [
        item
        for path in files
        for item in fingerprints_source(path.read_text(encoding="utf-8-sig"), path.relative_to(root).as_posix())
    ]
    folders, source_files = repository_inventory(project_cfg.BASE_DIR)
    suppressions = suppression_issues(root)
    artifacts = project_cfg.component("shared").generated_dir / "code_review" / str(time.time_ns())
    artifacts.mkdir(parents=True, exist_ok=False)
    status = report(
        results,
        len(files),
        folders,
        source_files,
        artifacts,
        duplicate_groups(fingerprints),
        suppressions,
        dependencies,
    )
    return int(bool(suppressions) or status)


if __name__ == "__main__":
    raise SystemExit(main())
