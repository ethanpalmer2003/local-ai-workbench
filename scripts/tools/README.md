# Repository tools

- `capability_matrix.py` regenerates `scripts/tests/notes/CAPABILITY-MATRIX.md` from recorded run evidence: the last run of each long opt-in check, the numbers it recorded, a link to its report, and `[WARN]` when a recorded build, weight or corpus no longer matches what is installed. `--check` lists what needs a rerun without writing.
- `fix_low_integrity.ps1` scans a path for a Low mandatory integrity label and repairs it, which is why Electron apps can crash at launch while the DACL still looks permissive. `-Mode Check` reports only; the cause and agent consequences are in [ELECTRON-LOW-INTEGRITY-CRASH.md](../../.agents/ELECTRON-LOW-INTEGRITY-CRASH.md).
- `stage_runner.py` runs long stages one at a time behind a single progress bar: each stage is a module command with an expected duration, tagged child lines (`[OK]`, `[FAIL]`, `[SKIP]`, `[TIME]`) appear as they happen, `[PROGRESS] n/m` lines drive the count, and a stage above its high mark is reported as slow. The validation runner and any new long job can use it, and one command can be wrapped as `python -m scripts.tools.stage_runner MODULE [ARGS...] --stage-known KEY`, which keeps every line the command prints.
- `stage_times.py` owns the expected ranges the runner compares against; `--stage-known` takes its key.
- `model_admin.py` resolves a catalog model to every catalog/runtime/workflow/Strata reference and source mention. Dry-run is the default. `--apply` edits the catalog file that owns the label (tracked catalog or private overlay), regenerates `models/ids.py` from the tracked catalog, rewrites active runtime/config references for `replace` (add `--include-docs`/`--include-tests` for maintained docs/tests), and moves weights to `C:/AI/trash`. `remove` refuses while runtime references remain; Strata native configs are a manual boundary. Weights are never physically deleted: installed files are moved to `C:/AI/trash/model_admin/<timestamp>/`; after manual deletion the catalog/reference cleanup still runs. The trash is emptied manually when the space is wanted back.
- `rocm_inventory.py` lists every ROCm install it can find (AMD program folder, the data runtime folder, framework `rocm` folders, AudioCpp additions) with kind, version marker, size, PATH state and which project path consumes it, so a cleanup decision starts from facts. `--json` for scripting, `--no-sizes` for a fast list.
- `state_cleanup.py` prunes regenerable state: `_MEI*` extractions a killed one-file executable left in the launch temp dir, `*.incomplete`/`*.lock` from aborted downloads, and run logs past `--log-days`. Defaults are 7 days for temp/download leftovers and 30 for logs; `--dry-run` previews. Launchers also prune stale `_MEI*` on start, so it only needs running after heavy use.
- `rewrite_imports.py` rewrites imports after moving Python modules. It uses
  explicit dotted-module mappings and also updates matching dotted references in
  Python source, including dynamic import paths.
- Preview changes with `--dry-run` before applying them. Run from `C:/AI`:

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tools.rewrite_imports --root scripts --dry-run --move old.module=new.module
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tools.rewrite_imports --root scripts --move old.module=new.module
```

