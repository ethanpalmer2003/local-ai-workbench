# Folders

- Keys and native-layout overrides: `COMPONENTS` in `scripts/config/project_config.py`; reuse a key where ownership matches, since a mirror folder has no owner.

| Role | Root + component key |
| --- | --- |
| Install | `frameworks/` |
| Environment | `.venv/` at the repo root, from `uv sync` |
| Model | `data/huggingface/models/` |
| Editable config | `scripts/config/`; model catalogs in `models/`, cross-component settings in `shared/`, shared guides in `notes/` |
| Launcher | Component launchers live under `scripts/launchers/<component>/`; shared helpers are grouped by purpose under `shared/`; cross-backend readiness, diagnostics and GPU policy use `runtime/`; role-wide plumbing stays at the launcher root. |
| Cross-role helpers | `scripts/shared/` when a launcher, a benchmark and a test all call the same module; a helper one role owns stays with that role |
| Repository tools | `scripts/tools/` |
| Repository review checks | `scripts/review/` |
| Test source / UI | `scripts/tests/cases/`, `scripts/tests/ui/` |
| Benchmark source / new results | `scripts/benchmarks/`, `scripts/benchmarks/output/` |
| Batch entry | `bat/update_frameworks.bat`; coding-agent launchers may sit at the `bat/` root, other routines group by role |
| App state | `scripts/state/` |
| New logs/cache/generated | `scripts/state/{logs,cache,generated}/` |

## Naming and grouping

- The layout check audits file types in the root and each role root.
- Settings: component first; `_SERVICE`, `_CLIENT` and `_ASR` state the role; `_DIR` binds a `Path` and `_BIN_DIR` an executable, converted at external boundaries.
- Group by purpose, not count; adapters stay with their owner. Keep a small folder that carries ownership, native layout or output identity; counts are prompts, not orders.
- A role that owns a module keeps it at that role's root, even when another role calls it: a benchmark area owns its corpus, scoring and reporting modules, and tests import them as clients. `scripts/shared/` is for modules no role owns, so no role tree needs a `shared` folder of its own.
- A name states its scope: a folder says the workload or engine, an entry point says what it runs, and a document uses an uppercase common noun. Widen the behavior, not the name; `tests` is test code only and vendor scripts keep their names.
- Historical results and logs keep their paths; `CasePaths` mirrors sources without empty parallel folders.
- Exceptions are explicit in `COMPONENTS`/`MODEL_ALIASES`: shared llama.cpp/Kobold installs, native app casing, ComfyUI typed storage. Preserve portable data, junctions, shared weights and vendor archive internals.

## Moves

- A move updates every consumer in the same change: imports, settings, catalogs, native preferences, batches and docs; keep sessions and evidence.
- Guard: the layout check; full review and commands: [checks](CHECKS.md).
