"""Report both code index sizes from their live stores, so no document has to quote them.

Codebase Memory counts come from its sqlite database, Graphify counts from graph.json; either
row reports itself missing instead of failing when its store is absent.
"""

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.tables import render_table

CBM_DB = Path.home() / ".cache" / "codebase-memory-mcp" / "C-AI.db"
GRAPH_JSON = project_cfg.GRAPHIFY_OUT_DIR / "graph.json"


@dataclass
class Index:
    name: str
    nodes: int
    edges: int
    groups: str
    detail: str


def _missing(name: str, detail: str) -> Index:
    return Index(name, 0, 0, "-", detail)


def codebase_status(db: Path = CBM_DB) -> Index:
    """Node and edge counts for this repository's Codebase Memory project, plus its indexed files."""
    try:
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return _missing("codebase-memory", f"no readable database at {db}")
    try:
        with connection:
            rows = connection.execute("select name, root_path from projects").fetchall()
            match = next(
                (name for name, path in rows if Path(path).as_posix() == project_cfg.BASE_DIR.as_posix()), None
            )
            if match is None:
                return _missing("codebase-memory", "this repository is not indexed")
            nodes = connection.execute("select count(*) from nodes where project = ?", (match,)).fetchone()[0]
            edges = connection.execute("select count(*) from edges where project = ?", (match,)).fetchone()[0]
            files = connection.execute(
                "select count(distinct file_path) from nodes where project = ?", (match,)
            ).fetchone()[0]
            updated = connection.execute("select indexed_at from projects where name = ?", (match,)).fetchone()
    except sqlite3.Error:
        return _missing("codebase-memory", f"no readable database at {db}")
    finally:
        connection.close()
    detail = f"{files} files, indexed {updated[0]}" if updated else f"{files} files"
    return Index("codebase-memory", nodes, edges, f"{files} files", detail)


def graphify_status(graph: Path = GRAPH_JSON) -> Index:
    """Node, edge and community counts from the current graph.json, plus the covered files."""
    try:
        data = json.loads(graph.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _missing("graphify", f"no readable graph at {graph}")
    nodes = data.get("nodes", [])
    communities = {node.get("community", "?") for node in nodes if isinstance(node, dict)}
    manifest = graph.parent / "manifest.json"
    try:
        files = len(json.loads(manifest.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        files = 0
    commit = str(data.get("built_at_commit") or "")[:12]
    return Index(
        "graphify",
        len(nodes),
        len(data.get("links", [])),
        f"{len(communities)} communities",
        f"{files} files, commit {commit}" if commit else f"{files} files",
    )


def status() -> list[Index]:
    return [codebase_status(), graphify_status()]


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable rows")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    rows = status()
    if args.json:
        print(json.dumps([asdict(row) for row in rows], indent=2))
        return 0
    print(
        render_table(
            [[row.name, str(row.nodes), str(row.edges), row.groups, row.detail] for row in rows],
            ["index", "nodes", "edges", "groups", "detail"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
