# Code search on this machine

Two graph tools answer structural questions, and both are installed and active in the desktop profile. Neither
ranks with a neural embedding model: Codebase Memory adds an FTS5 table and token vectors but loads no model,
Graphify is AST extraction only, so semantic near-duplicate work still belongs to
[similarity](../scripts/review/similarity.py).

| Tool | Install | Index | Query |
| --- | --- | --- | --- |
| Codebase Memory (`cbm_*` tools) | `uv tool install codebase-memory-mcp`, then toggle the bundle so the plugin resolves the runtime | `codebase-memory-mcp cli index_repository '{"repo_path": "C:/AI"}'`; 6 s for 7,460 nodes and 36,025 edges; excludes `.git`, `.venv`, `data`, `.pytest_cache`, `node_modules`; UI on `http://localhost:9749/` | `cbm_trace`, `cbm_search`, `cbm_snippet`, `cbm_arch` |
| Graphify (`dsh-graphify`, `graphify` CLI) | plugin bundle plus `uv tool install 'graphifyy[mcp]'` | `graphify update <repo> --no-cluster`, then `cluster-only --no-label`; 654 files, 6,168 nodes, 379 communities, no model needed | `graphify affected`, `god-nodes`, `path`, `explain`; `query` needs community labels |

Default choice: Codebase Memory for callers, snippets and name lookup; Graphify for architecture, hubs and
shortest paths; `git grep` and `git ls-files` for text and filenames. Nothing in this file forces a search
method; it records what each measured best at.

Measured on this repository: for `http_ready`, `cbm_trace` inbound reported 62 callers where `graphify affected`
at depth 2 reported 11, so Codebase Memory is the better caller tool and Graphify the better architecture map.

## Keeping the indexes current

Both are snapshots taken when a command runs. Nothing watches this repository: the plugin never constructs the
`RepositoryWatcher` it ships, a probe file added mid-session was still absent from `cbm_search` afterwards, and
`index_status` reported `watched: false` with the timestamp unchanged. A stale index answers confidently about
code that has moved, so a commit refreshes them: `scripts/tools/refresh_index.py` is a `post-commit` hook that
runs both indexers in parallel and skips graphify when the commit touched no file it extracts.
`python -m scripts.tools.refresh_index [--paths ...]` runs it by hand, and `pre-commit install --hook-type
post-commit` writes the hook into a fresh clone. A docs-only commit costs about 5 s and a code commit about 24 s,
of which graphify is 23 s.

1. Codebase Memory: `codebase-memory-mcp cli index_repository --repo-path C:/AI --mode fast` rewrites
   `~/.cache/codebase-memory-mcp/C-AI.db` (21 tables: `nodes`, `edges`, `nodes_fts`, `node_vectors`,
   `token_vectors`); 7,463 nodes and 36,032 edges in 2 to 4 s.
2. Graphify: `graphify update C:/AI --no-cluster`, then `graphify cluster-only C:/AI --no-label --no-viz`;
   6,170 nodes, 18,417 edges and 362 communities, code only. It re-extracts 40-odd files every run, so the
   cost is flat rather than proportional to the change.
3. Upgrades are separate from refreshes: `codebase-memory-mcp update -y` replaces the versioned binary the
   `~/.local/bin` shim points at, `graphify` updates as a uv tool, and the two DSH bundles through
   [plugin_manager](../.agents/DEEPSEEK-HARNESS.md).

Semantic ranking exists but is unused. `CBM_SEMANTIC_ENABLED` gates a pass that `index_repository --mode
full|moderate` runs and `fast` skips; it saves per-token vectors weighted by IDF and scores per keyword with a
minimum cosine, no model file and no server. The `cbm_*` tools never send `semantic_query`, and on `http_ready`
that ranking returned 0.03 against its 0.75 threshold.

Text search: prefer `git grep` or a tracked-file list (`git ls-files`, 729 files in 0.06 s) over a filesystem
walk. A walk from this root also descends into `data/`, `frameworks/` and `scripts/state/` and had not finished
after 60 s, which is why an unscoped search feels slow; pointing one at a directory with an include filter is
the fast path. Blocking the root is unnecessary when the search reads tracked files.
