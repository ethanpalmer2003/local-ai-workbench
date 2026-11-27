# Folders

- Keys and native-layout overrides: `COMPONENTS` in `scripts/config/project_config.py`; reuse a key where ownership matches, since a mirror folder has no owner.

| Role | Root + component key |
| --- | --- |
| Install | `frameworks/` |
| Environment | `.venv/` at the repo root, from `uv sync` |
| Model | `data/huggingface/models/` |
| Download | `scripts/download/`: installers and their catalogs |
| Editable config | `scripts/config/`; model catalogs in `models/`, cross-component settings in `common/`, shared guides in `notes/` |
| Launcher | Component launchers live under `scripts/launchers/<component>/`; shared helpers are grouped by purpose under `shared/`; cross-backend readiness, diagnostics and GPU policy use `runtime/`; role-wide plumbing stays at the launcher root. |
| Cross-role helpers | `scripts/shared/` when a launcher, a benchmark and a test all call the same module; a helper one role owns stays with that role |
| Repository tools | `scripts/tools/` |
| Repository review checks | `scripts/review/` |
| Test source / UI | `scripts/tests/cases/`, `scripts/tests/ui/` |
| Benchmark source / new results | `scripts/benchmarks/`, `runs/benchmarks/` |
| Batch entry | `bat/update_frameworks.bat`; routines group by role, with root batches and the indexed wrappers excepted |
| App state | `state/` for app data, with new logs, caches and generated pages under `state/{logs,cache,generated}/` |

## Local only

Two ignore files split the untracked tree: the root file holds the heavyweight trees, [`scripts/.gitignore`](../scripts/.gitignore) the folders its code writes. None of it ships: hundreds of gigabytes, all rebuildable but the input overlay and `trash/`.

| Path | Holds |
| --- | --- |
| `data/` | Weights, video-gen media, SDKs, generated audio/image/video, private input overlay |
| `frameworks/` | Installed engines |
| `trash/` | Moved-out files; the only removal path for nonempty data |
| `.venv/` | The interpreter |
| `state/` | Logs, caches, generated reports, app state |
| `runs/benchmarks/`, `runs/tests/` | Run evidence and temp workspaces |
| `scripts/.env` | Local credentials |
| `.zed/`, `.coverage`, `*.lnk` | Editor and tool state |
- Tool caches live under `runs/state/cache/pytest` and `runs/state/cache/ruff`; `__pycache__/` stays beside sources.
- Cited evidence stays here; [open questions](../notes/OPEN-QUESTIONS.md) covers shipping a subset.

## Naming and grouping

- The layout check audits file types in the root and each role root.
- Settings: component first; `_SERVICE`, `_CLIENT` and `_ASR` state the role; `_DIR` binds a `Path` and `_BIN_DIR` an executable.
- Group by purpose. A folder holds at most 20 direct files, and one file alone fails: it belongs to the parent. `__init__.py` does not count: a one-module package reads as one file. Below four it is a merge candidate unless it owns a purpose, a layout or an output identity.
- A role that owns a module keeps it at that role's root even when another role calls it: a benchmark area owns its corpus, scoring and reporting modules. `scripts/shared/` is for modules no role owns, so no role tree needs its own `shared`.
- A name states its scope: a folder says the workload or engine, an entry point says what it runs, and a document uses an uppercase common noun. Widen the behavior, not the name; `tests` is test code only and vendor scripts keep their names.
- Historical results keep their paths; `CasePaths` mirrors sources without empty parallel folders.
- Exceptions are explicit in `COMPONENTS`/`MODEL_ALIASES`: shared llama.cpp/Kobold installs, native app casing, ComfyUI typed storage. Preserve portable data, junctions, shared weights and vendor archive internals.

## Moves

- A move updates every consumer in the same change: imports, settings, catalogs, native preferences, batches and docs; keep sessions and evidence.
- Guard: the layout check; full review and commands: [checks](CHECKS.md).
