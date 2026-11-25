"""Every runnable entry point under tools/ and review/: what it is for, kept current by test.

Kinds are report (reads and prints, changes nothing), check (judges, non-zero on findings),
generate (writes derived files), and act (changes state, installs, or runs things). A new main()
fails test_entry_points until it is classified here, so the census never silently goes stale.
Descriptions come from each module's own docstring, so there is nothing else to update.
"""

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.tables import render_table

# - dotted module to kind; the scanner in test_entry_points derives the same keys from source
ALL: dict[str, str] = {
    "scripts.review": "check",
    "scripts.review.checks.annotations": "check",
    "scripts.review.checks.bare_any": "check",
    "scripts.review.checks.comments": "check",
    "scripts.review.checks.dead_code": "check",
    "scripts.review.checks.docs": "check",
    "scripts.review.checks.duplicates": "check",
    "scripts.review.checks.dynamic_imports": "check",
    "scripts.review.checks.expression": "check",
    "scripts.review.checks.frontend_wiring": "check",
    "scripts.review.checks.inventory_code": "check",
    "scripts.review.checks.layout": "check",
    "scripts.review.checks.line_length": "check",
    "scripts.review.checks.model_references": "check",
    "scripts.review.checks.network_timeouts": "check",
    "scripts.review.checks.overlay_access": "check",
    "scripts.review.checks.owned_tokens": "check",
    "scripts.review.checks.similarity": "check",
    "scripts.review.checks.spellings": "check",
    "scripts.review.checks.typography": "check",
    "scripts.review.checks.walrus": "check",
    "scripts.review.format_py": "act",
    "scripts.review.handoff": "generate",
    "scripts.review.limits": "report",
    "scripts.review.lists.entry_points": "report",
    "scripts.review.lists.index_status": "report",
    "scripts.review.lists.manual_gates": "report",
    "scripts.review.output_lines": "check",
    "scripts.review.restrictions": "report",
    "scripts.review.ruff_ignores": "report",
    "scripts.review.tree_sizes": "report",
    "scripts.review.voice_references": "report",
    "scripts.tools.capability_matrix": "generate",
    "scripts.tools.cleanup": "act",
    "scripts.tools.language_matrix": "generate",
    "scripts.tools.local_work": "report",
    "scripts.tools.locate_files": "report",
    "scripts.tools.low_integrity": "check",
    "scripts.tools.model_admin": "act",
    "scripts.tools.probe_runner": "act",
    "scripts.tools.python_upgrade": "check",
    "scripts.tools.refresh_index": "act",
    "scripts.tools.rename_path": "act",
    "scripts.tools.rewrite_imports": "act",
    "scripts.tools.rocm_inventory": "report",
    "scripts.tools.sample_code": "generate",
    "scripts.tools.stage_runner": "act",
    "scripts.tools.state_cleanup": "act",
    "scripts.tools.strata_profile": "check",
    "scripts.tools.yaml_table": "report",
}

ROOTS = (
    project_cfg.SCRIPTS_DIR / "tools",
    project_cfg.SCRIPTS_DIR / "review",
    project_cfg.SCRIPTS_DIR / "review" / "lists",
    project_cfg.SCRIPTS_DIR / "review" / "checks",
)

KINDS = ("report", "check", "generate", "act")


@dataclass(frozen=True)
class EntryPoint:
    module: str
    kind: str
    summary: str


def _dotted(path: Path) -> str:
    """The -m name for a file under scripts/: review/__main__.py runs as scripts.review."""
    relative = path.relative_to(project_cfg.BASE_DIR).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__main__":
        parts.pop()
    return ".".join(parts)


def discovered() -> list[str]:
    """Every module with a main() under the command roots, derived from source."""
    found = []
    for root in ROOTS:
        for path in root.glob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            if any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in ast.walk(tree)):
                found.append(_dotted(path))
    return sorted(found)


def _source(module: str) -> Path | None:
    """The file behind a dotted name; scripts.review runs as its __main__ module."""
    if module == "scripts.review":
        module = "scripts.review.__main__"
    path = project_cfg.BASE_DIR / Path(*module.split(".")).with_suffix(".py")
    return path if path.is_file() else None


def _summary(module: str) -> str:
    """The module docstring's first line; empty when the module has none."""
    path = _source(module)
    if path is None:
        return ""
    try:
        text = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    except (OSError, SyntaxError):
        return ""
    return text.splitlines()[0] if text else ""


def entries(kind: str | None = None) -> list[EntryPoint]:
    """The registered entry points, optionally filtered to one kind."""
    return [
        EntryPoint(module, entry_kind, _summary(module))
        for module, entry_kind in sorted(ALL.items())
        if kind is None or entry_kind == kind
    ]


def report(kind: str | None = None) -> str:
    """The census as an aligned table, for the console or an answer."""
    return render_table(
        [[entry.module, entry.kind, entry.summary] for entry in entries(kind)], ["module", "kind", "summary"]
    )


def counts() -> dict[str, int]:
    """How many entry points of each kind; the answer to how many doc functions we have."""
    return {kind: sum(1 for entry_kind in ALL.values() if entry_kind == kind) for kind in KINDS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=[*KINDS], help="only one kind of entry point")
    parser.add_argument("--count", action="store_true", help="print kind counts instead of the table")
    args = parser.parse_args(argv)
    if args.count:
        print(" ".join(f"{kind}={total}" for kind, total in counts().items()))
        return 0
    print(report(args.kind))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
