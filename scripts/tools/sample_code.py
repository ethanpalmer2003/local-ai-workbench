"""Assemble one review sample: a module in full, then the definitions from its owners that carry its rule.

A reader outside the repository cannot follow a rule that calls into a file they do not have, so each
owner's definitions arrive under one header, and the footer names what was copied and what the excerpt
still needs. The output is a text file, not a document: evidence for a reader, not a rule.
"""

import argparse
import ast
import builtins
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


def _named(node: ast.AST) -> str | None:
    """The name a definition binds, when the node is a kind that binds one."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.ExceptHandler):
        return node.name
    return None


def _top_level(tree: ast.Module) -> set[str]:
    """Every name a module defines at top level."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
        elif name := _named(node):
            names.add(name)
    return names


def _imported(tree: ast.Module) -> dict[str, str]:
    """Every name a module imports, mapped to the module it comes from."""
    origins: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            origins.update((alias.asname or alias.name, node.module) for alias in node.names)
        elif isinstance(node, ast.Import):
            origins.update((alias.asname or alias.name.split(".")[0], alias.name) for alias in node.names)
    return origins


def _used(source: str) -> set[str]:
    """Every name some source mentions, arguments and attributes aside."""
    return {node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)}


def _local(source: str) -> set[str]:
    """Every name some source binds for itself, so it needs nothing brought in."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif name := _named(node):
            names.add(name)
    return names


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


def unaccounted(bodies: list[str], known: set[str], owners: list[Path]) -> list[str]:
    """Names the copied code still needs, each with the module it comes from."""
    origins: dict[str, str] = {}
    for owner in owners:
        tree = ast.parse(owner.read_text(encoding="utf-8"))
        origins.update(dict.fromkeys(_top_level(tree), display_path(owner)))
        origins.update(_imported(tree))
    used = set().union(*(_used(body) for body in bodies))
    local = set().union(*(_local(body) for body in bodies))
    missing = sorted((used - local - known) - set(dir(builtins)))
    return [f"{name} from {origins.get(name, 'an owner not copied')}" for name in missing]


def build(module: Path, includes: list[tuple[Path, str]], title: str = "") -> str:
    """The whole sample: an optional title line, the module, one block per owner, and the accounting."""
    text = module.read_text(encoding="utf-8")
    grouped: dict[Path, list[tuple[str, str]]] = {}
    for path, name in includes:
        grouped.setdefault(path, []).append((name, definition(path, name)))
    bodies = [source for entries in grouped.values() for _name, source in entries]
    blocks = [text.rstrip("\n")]
    for path, entries in grouped.items():
        header = f"# - copied from {display_path(path)} so the rule above can be read without it."
        blocks.append(f"{header}\n" + "\n\n\n".join(source for _name, source in entries))
    copied = {name for _path, name in includes}
    known = _top_level(ast.parse(text)) | copied
    left_out = unconsumed(module, copied) + unaccounted(bodies, known, list(grouped))
    footer = [
        f"# - copied in: {', '.join(name for name, _source in entries)} from {display_path(path)}"
        for path, entries in grouped.items()
    ]
    footer.extend(f"# - left out: {item}" for item in sorted(set(left_out)))
    tail = "\n".join(footer)
    body = "\n\n\n".join(blocks) + (f"\n\n{tail}" if footer else "") + "\n"
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
