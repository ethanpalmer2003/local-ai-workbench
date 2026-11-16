# Code search on this machine

Two graph tools answer structural questions, and both are installed and active in the desktop profile. Neither
uses embeddings: they are AST and call-graph indexes, so semantic near-duplicate work still belongs to
[similarity](../scripts/review/similarity.py).

| Tool | Install | Index | Query |
| --- | --- | --- | --- |
| Codebase Memory (`cbm_*` tools) | `uv tool install codebase-memory-mcp`, then toggle the bundle so the plugin resolves the runtime | `codebase-memory-mcp cli index_repository '{"repo_path": "C:/AI"}'`; 6 s for 7,460 nodes and 36,025 edges; excludes `.git`, `.venv`, `data`, `.pytest_cache`, `node_modules`; UI on `http://localhost:9749/` | `cbm_trace`, `cbm_search`, `cbm_snippet`, `cbm_arch` |
| Graphify (`dsh-graphify`, `graphify` CLI) | plugin bundle plus `uv tool install 'graphifyy[mcp]'` | `graphify update <repo> --no-cluster`, then `cluster-only --no-label`; 654 files, 6,168 nodes, 379 communities, no model needed | `graphify affected`, `god-nodes`, `path`, `explain`; `query` needs community labels |

Measured on this repository: for `http_ready`, `cbm_trace` inbound reported 62 callers where `graphify affected`
at depth 2 reported 11, so Codebase Memory is the better caller tool and Graphify the better architecture map.

Text search: prefer `git grep` or a tracked-file list (`git ls-files`, 729 files in 0.06 s) over a filesystem
walk. A walk from this root also descends into `data/`, `frameworks/` and `scripts/state/` and had not finished
after 60 s, which is why an unscoped search feels slow; pointing one at a directory with an include filter is
the fast path. Blocking the root is unnecessary when the search reads tracked files.
