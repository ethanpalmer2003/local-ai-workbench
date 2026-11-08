# Repository tools

- `capability_matrix.py` regenerates `scripts/tests/notes/CAPABILITY-MATRIX.md` from recorded run evidence: the last run of each long opt-in check, the numbers it recorded, a link to its report, and `[WARN]` when a recorded build, weight or corpus no longer matches what is installed. `--check` lists what needs a rerun without writing.
- `fix_low_integrity.ps1` scans a path for a Low mandatory integrity label and repairs it, which is why Electron apps can crash at launch while the DACL still looks permissive. `-Mode Check` reports only; the cause and agent consequences are in [ELECTRON-LOW-INTEGRITY-CRASH.md](../../.agents/ELECTRON-LOW-INTEGRITY-CRASH.md).
- `model_admin.py` resolves a catalog model to every catalog/runtime/workflow/Strata reference and source mention. Dry-run is the default. `--apply` edits `models/catalog.json`, regenerates `models/ids.py`, rewrites active runtime/config references for `replace` (add `--include-docs`/`--include-tests` for maintained docs/tests), and moves weights to `C:/AI/trash`. `remove` refuses while runtime references remain; Strata native configs are a manual boundary. Weights are never physically deleted: installed files are moved to `C:/AI/trash/model_admin/<timestamp>/`; after manual deletion the catalog/reference cleanup still runs. The trash is emptied manually when the space is wanted back.
- `state_cleanup.py` prunes regenerable state: `_MEI*` extractions a killed one-file executable left in the launch temp dir, `*.incomplete`/`*.lock` from aborted downloads, and run logs past `--log-days`. Defaults are 7 days for temp/download leftovers and 30 for logs; `--dry-run` previews. Launchers also prune stale `_MEI*` on start, so it only needs running after heavy use.
- `rewrite_imports.py` rewrites imports after moving Python modules. It uses
  explicit dotted-module mappings and also updates matching dotted references in
  Python source, including dynamic import paths.
- Preview changes with `--dry-run` before applying them. Run from `C:/AI`:

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tools.rewrite_imports --root scripts --dry-run --move old.module=new.module
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tools.rewrite_imports --root scripts --move old.module=new.module
```

