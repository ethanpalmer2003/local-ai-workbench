# Repository review

Run the complete review from `C:/AI`:

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.review
C:/AI/scripts/review/check_repo.bat
```

The runner executes these checks:

- `structure_docs.py`: component/config ownership, path/link validity, maintained Markdown budgets, Markdown basename casing, and document roles.
- `model_references.py`: catalog IDs, workflow defaults, and AudioCpp runtime IDs/paths.
- `frontend_wiring.py`: front-end wiring: HTML/JS asset paths, DOM element ids and injected settings keys.
- `basedpyright`: Python type errors.
- `inventory_code.py`: folder counts, sparse-folder warnings, 2-3-item merge candidates, Markdown/Python-module counts, file lines and function size for context; the gate is ruff's McCabe rule. Python-module counts exclude `__init__.py`; low counts are prompts to review, not automatic merge findings.
- `typography.py`: ASCII punctuation only: em and en dashes, curly quotes, the ellipsis and no-break spaces are rejected in every tracked text file, quoted corpus references excepted. It gates, and the pre-commit hook runs the same module on staged files.

Reports go to `scripts/state/generated/shared/code_review/<run>/`. Function complexity is gated by ruff at McCabe 10; the inventory lists the largest functions for context. Inventory excludes generated output, caches, model data, third-party installations and trash.

Run a single check with `python -m scripts.review.structure_docs`, `python -m scripts.review.model_references`, `python -m scripts.review.frontend_wiring`, or `python -m scripts.review.inventory_code`. `structure_docs --words` prints every maintained document by word count with its budget, `--roles` counts documents per role, and `--links` reports pointers, repeats and unlinked documents. A link into an untracked path fails, since a clone would carry a dead link; repeats are advisory. Document organization lives in [NOTES-CONVENTIONS](../../.agents/NOTES-CONVENTIONS.md).

## Framework validation

This gate is repo-wide and never loads a model. A check that belongs to one framework stays beside that
component:

| Check | Location | Runs at |
| --- | --- | --- |
| Startup contract | `config/<component>/verify*.py`, e.g. [verify_node.py](../config/comfyui/verify_node.py) | launcher |
| Offline contract | `tests/cases/<component>/` | model-free suite |
| Update check | [framework updates](../download/frameworks/UPDATES.md), driven by `update_shared.py` | update run |
| Live preflight | [benchmarks/shared/preflight.py](../benchmarks/shared/preflight.py) | benchmark run |

A framework without a startup validator makes its launcher fail on missing paths instead.

## Front-end wiring (`frontend_wiring.py`)

Static and literal-only; it never executes the pages.

- Asset paths: HTML `<script src>`/`<link href>` and JS `path.join`/`path.resolve` calls. A base variable derived from `__dirname`, and loop variables bound to a literal array, are resolved; computed or templated paths are skipped rather than guessed. Because the page is served at a shallow URL (`/test/`), an HTML reference also resolves once its leading `../` segments are stripped and matched under `scripts/`.
- DOM ids: ids an inline script reads via `getElementById`/`querySelector('#id')` must be defined in the same HTML; external scripts are not scanned.
- Settings keys: each row of `SETTINGS_CONTRACTS` pairs a launcher's injected `window.<object>` with its reader scripts and test fixture. Reads the launcher never emits, or (ignoring `||`/`??` fallbacks) the fixture never provides, are reported. Add a row per injected settings object.

Format the whole repository with `scripts/review/format_py.bat`. Lint and format share one scope: repository root, Python files only, with `.venv`, `frameworks`, `data`, `trash`, `scripts/state`, run outputs and generated `ids.py` excluded. The gate compares formatting too; `--no-format-check` skips it. Tool inventory: [TOOLS.md](TOOLS.md).
