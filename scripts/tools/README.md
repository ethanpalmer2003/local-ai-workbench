# Repository tools

- `capability_matrix.py` regenerates `scripts/tests/notes/GENERATED-CAPABILITY-MATRIX.md` from recorded run evidence: the last run of each long opt-in check, its numbers, a report link, and `[WARN]` when a recorded build, weight or corpus no longer matches what is installed. A row is judged only when its report carries provenance from `reporting.record_inputs`; `[defer]` marks work parked on purpose, and `--check` lists what needs a rerun without writing.
- `fix_low_integrity.ps1` repairs a Low mandatory integrity label, which crashes Electron apps at launch while the DACL still looks permissive. `-Mode Check` reports only; the cause is in [ELECTRON-LOW-INTEGRITY-CRASH.md](../../.agents/ELECTRON-LOW-INTEGRITY-CRASH.md).
- `language_matrix.py` renders `scripts/config/notes/GENERATED-LANGUAGE-MATRIX.md` from `model_languages.json`: declared support only, every ASR and TTS checkpoint against the practice languages, unknown left unknown. Its input is tracked, so a model-free test fails when the page goes stale; the capability matrix reads untracked evidence, so its page is a snapshot and re-rendering stays a decision.
- `yaml_table.py` prints a YAML list of mappings as a table, which is how hand-kept data is read without a generated page: parked work, the input overlay, voice sources. `--columns` picks and orders keys, `--markdown` emits a GitHub table, and column order is the order the records introduce their keys.
- `probe_runner.py` runs a capability module under a hard wall-clock deadline and kills it when the budget passes (`ProbeTimeout`, exit 124), because inner timeouts bound one read only. Budgets are per category (smoke 90 s, probe 300 s, benchmark 900 s) from the table in the tool; `--category` or `--deadline` overrides one run.
- `stage_runner.py` runs long stages behind one progress bar: each stage is a module command with an expected duration, `[PROGRESS] n/m` drives the count, and a stage above its high mark is reported as slow. Wrap one command as `python -m scripts.tools.stage_runner MODULE [ARGS...] --stage-known KEY`.
- `stage_times.py` owns the expected ranges the runner compares against; `--stage-known` takes its key.
- `cleanup.py` moves superseded run evidence to trash, weighting a benchmark above a fast suite run and never touching a cited run id; `--keep`/`--older-than` override the class, `--state` prunes regenerable state, and `--empty-trash DAYS` is the explicit door. The gate runs it after each run, so trash older than two days is deleted.
- `model_admin.py` resolves a catalog model to every reference and source mention; a dry run is the default. `--apply` edits the owning catalog, regenerates `models/ids.py`, rewrites active runtime/config references for `replace` (add `--include-docs`/`--include-tests` for maintained docs/tests), and moves weights to `C:/AI/trash`, where automatic pruning deletes them after two days. `remove` refuses while runtime references remain; Strata native configs are a manual boundary.
- `low_integrity.py` checks the Low integrity label in Python, reporting only unless `--fix`; `local_work.py` lists the saved HRX fixes, patches and local-only commits; `strata_profile.py` keeps Strata's profile folders as junctions into `state/strata`.
- `rocm_inventory.py` lists every ROCm install it finds (AMD program folder, data runtime, framework `rocm` folders, AudioCpp additions) with kind, version, size, PATH state and the project path that consumes it. `--json` for scripting, `--no-sizes` for a fast list.
- `state_cleanup.py` prunes regenerable state: `_MEI*` extractions a killed one-file executable left in the launch temp dir, `*.incomplete`/`*.lock` from aborted downloads, AudioCpp support-model folders past `--cache-days`, and run logs past `--log-days`. Defaults are 7 days for temp/download leftovers and 30 for logs and the model cache; `--dry-run` previews, and launchers also prune stale `_MEI*` at start. Prunable classes: `cache`, `logs`, `downloads`, `generated`, `temp`; the rest is application data.
- `rename_path.py` moves one tracked file or folder and repoints its references: `--move OLD=NEW` previews the count and files, and `--apply` with the consent flag runs `git mv` and rewrites every path and import spelling in Markdown, Python, batch, YAML and JSON, ending with `[WARN]` for what it could not reach. A bare basename is rewritten only beside the moved file. Modules move with `rewrite_imports.py`; the checks confirm.
- `python_upgrade.py` asks uv whether the dependencies resolve for another interpreter; `--install` proves the wheels in a scratch copy of the project.
- `sample_code.py` writes one review sample: a module in full, the definitions it calls from other owners copied in under one header per owner, and a footer naming what was copied and what is still needed. `--include FILE:NAME`, `--title`.
- `refresh_index.py` rebuilds the code indexes: call graph inline, graphify detached behind a lock and skipped for a docs-only commit, each exit code reported. Costs: [code search](../../.agents/CODE-SEARCH.md#keeping-the-indexes-current).
- `rewrite_imports.py` rewrites imports after moving Python modules. It uses
  explicit dotted-module mappings and also updates matching dotted references in
  Python source, including dynamic import paths.
- Preview changes with `--dry-run` before applying them. Run from `C:/AI`:

```powershell
python -m scripts.tools.rewrite_imports --root scripts --dry-run --move old.module=new.module
python -m scripts.tools.rewrite_imports --root scripts --move old.module=new.module
```

