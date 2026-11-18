"""Assemble one review sample: a module in full, then the definitions from its owners that carry its rule.

A reader outside the repository cannot follow a rule that calls into a file they do not have, so each
owner's definitions arrive under one comment naming where they live. The output is a text file, not a
document: evidence for a reader, not a rule.
"""

import argparse
import ast
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.paths import display_path


def definition(path: Path, name: str) -> str:
    """One top-level definition's own source, with the comment lines directly above it."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    node = next((item for item in ast.parse(text).body if _defines(item, name)), None)
    if node is None:
        raise SystemExit(f"{path}: no top-level function or constant named {name}")
    start = node.lineno - 1
    while start and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    return "\n".join(lines[start : node.end_lineno])


def _defines(node: ast.stmt, name: str) -> bool:
    """Whether this top-level statement names the definition a sample asked for."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name == name
    if isinstance(node, ast.Assign | ast.AnnAssign):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(isinstance(target, ast.Name) and target.id == name for target in targets)
    return False


def build(module: Path, includes: list[tuple[Path, str]], title: str = "") -> str:
    """The whole sample: an optional title line, the module, then one comment and block per owner."""
    text = module.read_text(encoding="utf-8")
    grouped: dict[Path, list[tuple[str, str]]] = {}
    for path, name in includes:
        grouped.setdefault(path, []).append((name, definition(path, name)))
    blocks = [text.rstrip("\n")]
    for path, entries in grouped.items():
        names = ", ".join(name for name, _source in entries)
        header = f"# - {names} lives in {display_path(path)}, copied here so the rule above can be read without it."
        blocks.append(f"{header}\n" + "\n\n\n".join(source for _name, source in entries))
    body = "\n\n\n".join(blocks) + "\n"
    # - a comment, so the sample stays valid Python even with a title for an attachment above it
    return f"# {title}\n\n{body}" if title else body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", help="file to reproduce in full, repo-relative")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="FILE:NAME",
        help="definition to copy in after the module; repeats from one file share a header",
    )
    parser.add_argument("--title", default="", help="one line above the code, for a reader or an attachment")
    parser.add_argument("--out", required=True, help="text file to write, repo-relative")
    args = parser.parse_args(argv)
    includes = []
    for item in args.include:
        path, _, name = item.partition(":")
        if not name:
            raise SystemExit(f"--include wants FILE:NAME, not {item}")
        includes.append((project_cfg.BASE_DIR / path, name))
    sample = build(project_cfg.BASE_DIR / args.module, includes, args.title)
    target = project_cfg.BASE_DIR / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sample, encoding="utf-8", newline="\n")
    print(f"[OK] Sample: {len(sample.splitlines())} lines -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
