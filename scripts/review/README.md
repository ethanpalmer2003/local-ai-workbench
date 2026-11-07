# Repository review

Run the complete review from `C:/AI`:

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.review
C:/AI/scripts/review/check.bat
```

The runner executes five checks:

- `structure.py`: component/config ownership, path/import/link validity and maintained Markdown budgets.
- `model_drift.py`: catalog IDs, workflow defaults, and AudioCpp runtime IDs/paths.
- `frontend.py`: front-end wiring - HTML/JS asset paths, DOM element ids and injected settings keys.
- `basedpyright`: Python type errors.
- `inventory.py`: folder counts, sparse-folder warnings, 2-3-item merge candidates, Markdown/Python-module counts, file lines, function complexity (depth 4 / 100 code lines, which gates) and duplicate function bodies (advisory). Python-module counts exclude `__init__.py`; low counts are prompts to review, not automatic merge findings.

Reports go to `scripts/state/generated/shared/code_review/<run>/`. Function limits are depth 4 and 100 code lines. Inventory excludes generated output, caches, model data, third-party installations and trash.

Run a single check with `python -m scripts.review.structure`, `python -m scripts.review.model_drift`, `python -m scripts.review.frontend`, or `python -m scripts.review.inventory`.

## Front-end wiring (`frontend.py`)

Static and literal-only; it never executes the pages.

- Asset paths: HTML `<script src>`/`<link href>` and JS `path.join`/`path.resolve` calls. A base variable derived from `__dirname`, and loop variables bound to a literal array, are resolved; computed or templated paths are skipped rather than guessed. Because the page is served at a shallow URL (`/test/`), an HTML reference also resolves once its leading `../` segments are stripped and matched under `scripts/`.
- DOM ids: ids an inline script reads via `getElementById`/`querySelector('#id')` must be defined in the same HTML; external scripts are not scanned.
- Settings keys: each row of `SETTINGS_CONTRACTS` pairs a launcher's injected `window.<object>` with its reader scripts and test fixture. Reads the launcher never emits, or (ignoring `||`/`??` fallbacks) the fixture never provides, are reported. Add a row per injected settings object.

Format the scripts tree with `scripts/review/format.bat`. The gate compares formatting too; `--no-format-check` skips it. Tool inventory: [TOOLS.md](TOOLS.md).
