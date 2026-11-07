# Folders

- Keys and native-layout overrides: `COMPONENTS` in `scripts/config/project_config.py`. Reuse a key where ownership matches; mirror folders are unnecessary.
- Resolve paths through `project_cfg.component()` and catalog helpers.

| Role | Root + component key |
| --- | --- |
| Install | `frameworks/` |
| Model | `data/huggingface/models/` |
| Editable config | `scripts/config/`; model catalogs in `models/`, cross-component settings in `shared/`, shared guides in `notes/` |
| Launcher | Component launchers live under `scripts/launchers/<component>/`; shared helpers are grouped by purpose under `shared/`; cross-backend readiness, diagnostics and GPU policy use `runtime/`; role-wide plumbing stays at the launcher root. |
| Repository tools | `scripts/tools/` |
| Repository review checks | `scripts/review/` |
| Test source / UI | `scripts/tests/cases/`, `scripts/tests/ui/` |
| Benchmark source / new results | `scripts/benchmarks/`, `scripts/benchmarks/output/` |
| Batch entry | `bat/update_frameworks.bat`; coding-agent launchers may sit at the `bat/` root, other routines group by role |
| App state | `scripts/state/` |
| New logs/cache/generated | `scripts/state/{logs,cache,generated}/` |

## Naming and grouping

- Settings: component first; `_SERVICE` for services, `_CLIENT` for coding clients, `_ASR` for ASR profiles. Directory bindings are `Path`; distinguish install, build, bin and SDK roles.
- Group by purpose, not count; native adapters stay with their owner. Avoid empty placeholders and one-item shells; keep a small folder that carries ownership, native layout or output identity. Audit counts are prompts, not orders.
- Historical results and logs keep their paths; `CasePaths` mirrors sources without empty parallel folders.
- Exceptions are explicit in `COMPONENTS`/`MODEL_ALIASES`: shared llama.cpp/Kobold installs, native app casing, ComfyUI typed storage. Preserve portable data, junctions, shared weights and vendor archive internals.

## Moves

- Update imports, settings, catalogs, native preferences, batches and docs together; record data moves, keep existing sessions.
- Guard: `python -m scripts.review.structure`; full review: `python -m scripts.review`.
