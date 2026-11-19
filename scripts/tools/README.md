# Repository tools

- `capability_matrix.py` regenerates `scripts/tests/notes/GENERATED-CAPABILITY-MATRIX.md` from recorded run evidence: the last run of each long opt-in check, the numbers it recorded, a link to its report, and `[WARN]` when a recorded build, weight or corpus no longer matches what is installed. A row is judged only when its report carries provenance, which producers add through `reporting.record_inputs`; `[defer]` marks work parked on purpose. `--check` lists what needs a rerun without writing.
- `fix_low_integrity.ps1` repairs a Low mandatory integrity label, which crashes Electron apps at launch while the DACL still looks permissive. `-Mode Check` reports only; the cause is in [ELECTRON-LOW-INTEGRITY-CRASH.md](../../.agents/ELECTRON-LOW-INTEGRITY-CRASH.md).
- `language_matrix.py` renders `scripts/config/notes/GENERATED-LANGUAGE-MATRIX.md` from `model_languages.json`: declared support only, every ASR and TTS checkpoint against the practice languages, with unknown left unknown. Its input is tracked, so a model-free test fails when the committed page goes stale; the capability matrix reads untracked run evidence instead, so its page is a snapshot and re-rendering stays a decision.
- `yaml_table.py` prints a YAML list of mappings as a table, which is how the hand-kept data files are read without a generated page: parked work in `config/shared/deferred.yaml`, the input overlay, voice sources. `--columns` picks and orders keys, `--markdown` emits a GitHub table. Column order is the order the records introduce their keys.
- `probe_runner.py` runs a capability module under a hard wall-clock deadline and kills it when the budget passes (`ProbeTimeout`, exit 124), because inner request timeouts only bound one read. Budgets are per category: smoke 90 s, probe 300 s, benchmark 900 s, with the module-to-category table in the tool; `--category` or `--deadline` overrides one run.
- `stage_runner.py` runs long stages behind one progress bar: each stage is a module command with an expected duration, tagged child lines appear as they happen, `[PROGRESS] n/m` drives the count, and a stage above its high mark is reported as slow. Wrap one command as `python -m scripts.tools.stage_runner MODULE [ARGS...] --stage-known KEY`.
- `stage_times.py` owns the expected ranges the runner compares against; `--stage-known` takes its key.
- `locate_files.py` lists files by suffix under the known roots in a depth-bounded walk; `tree_sizes.py` says which of those roots are expensive and covered.
- `tree_sizes.py` lists local trees with whether git ignores them and the profile guard covers them; `--measure` adds sizes from one robocopy pass.
- `model_admin.py` resolves a catalog model to every reference and source mention; a dry run is the default. `--apply` edits the owning catalog, regenerates `models/ids.py`, rewrites active runtime/config references for `replace` (add `--include-docs`/`--include-tests` for maintained docs/tests), and moves weights to `C:/AI/trash`. `remove` refuses while runtime references remain; Strata native configs are a manual boundary. Weights are moved, never deleted: installed files go to `C:/AI/trash/model_admin/<timestamp>/`, and the trash is emptied by hand when the space is wanted back.
- `rocm_inventory.py` lists every ROCm install it finds (AMD program folder, data runtime, framework `rocm` folders, AudioCpp additions) with kind, version, size, PATH state and the project path that consumes it. `--json` for scripting, `--no-sizes` for a fast list.
- `state_cleanup.py` prunes regenerable state: `_MEI*` extractions a killed one-file executable left in the launch temp dir, `*.incomplete`/`*.lock` from aborted downloads, AudioCpp support-model folders past `--cache-days`, and run logs past `--log-days`. Defaults are 7 days for temp/download leftovers and 30 for logs and the model cache; `--dry-run` previews, and launchers also prune stale `_MEI*` at start. Prunable classes: `cache`, `logs`, `downloads`, `generated`, `temp`; the rest is application data.
- `rename_path.py` moves one tracked file or folder and repoints its references: `--move OLD=NEW` previews the count and files, and `--apply` with the consent flag runs `git mv` and rewrites every path and import spelling in Markdown, Python, batch, YAML and JSON, ending with `[WARN]` for what it could not reach. A bare basename is rewritten only beside the moved file. Modules move with `rewrite_imports.py`; the checks confirm.
- `python_upgrade.py` asks uv whether the dependencies resolve for another interpreter; `--install` proves the wheels in a scratch environment.
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

