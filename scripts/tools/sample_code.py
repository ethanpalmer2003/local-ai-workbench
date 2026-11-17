"""Assemble one review sample: a module in full, plus the functions from its owners that carry its rule.

A reader outside the repository cannot follow a rule that calls into a file they do not have, so the
copied functions are labeled with where they live and the imports left out are listed with the one
thing each does. The output is a text file, not a document: it is evidence for a reader, not a rule.
"""

import argparse
import ast
from pathlib import Path

from scripts.config import project_config as project_cfg


def function_source(path: Path, name: str, note: str) -> str:
    """One top-level function's source, with a comment saying where it came from and why it is here."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    node = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name == name),
        None,
    )
    if node is None:
        raise SystemExit(f"{path}: no top-level function named {name}")
    relative = path.relative_to(project_cfg.BASE_DIR).as_posix()
    source = "\n".join(text.splitlines()[node.lineno - 1 : node.end_lineno])
    return f"# - copied from {relative} so the rule above can be read without it. {note}\n{source}"


def unconsumed(module: Path, shown: set[str]) -> list[str]:
    """Dotted imports this module reads that the sample does not include, grouped by owner."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    owners: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("scripts."):
            names = [alias.name for alias in node.names if alias.name not in shown]
            if names:
                owners.setdefault(node.module, []).extend(names)
    return [f"{', '.join(names)} from {owner}" for owner, names in sorted(owners.items())]


def build(module: Path, includes: list[tuple[Path, str]], note: str) -> str:
    """The whole sample: a header naming what is shown and what is not, then the code in reading order."""
    relative = module.relative_to(project_cfg.BASE_DIR).as_posix()
    lines = module.read_text(encoding="utf-8").splitlines()
    shown = {name for _path, name in includes}
    count = "1 function" if len(includes) == 1 else f"{len(includes)} functions"
    header = [
        f"# Sample: {relative} ({len(lines)} lines), plus {count} copied from its owners.",
        *[f"# - left out: {item}" for item in unconsumed(module, shown)],
        "",
    ]
    blocks = ["\n".join(lines)]
    blocks.extend(function_source(path, name, note) for path, name in includes)
    return "\n".join(header) + "\n\n\n".join(blocks) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", help="file to reproduce in full, repo-relative")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="FILE:FUNCTION",
        help="function to copy in after the module, with the file that owns it",
    )
    parser.add_argument("--note", default="", help="one sentence on why the copied function is here")
    parser.add_argument("--out", required=True, help="text file to write, repo-relative")
    args = parser.parse_args(argv)
    includes = []
    for item in args.include:
        path, _, name = item.partition(":")
        if not name:
            raise SystemExit(f"--include wants FILE:FUNCTION, not {item}")
        includes.append((project_cfg.BASE_DIR / path, name))
    sample = build(project_cfg.BASE_DIR / args.module, includes, args.note)
    target = project_cfg.BASE_DIR / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sample, encoding="utf-8", newline="\n")
    print(f"[OK] Sample: {len(sample.splitlines())} lines -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
