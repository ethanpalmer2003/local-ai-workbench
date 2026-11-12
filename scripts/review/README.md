# Repository review

Run the complete review from `C:/AI`:

```powershell
python -m scripts.review
C:/AI/scripts/review/check_repo.bat
```

The gate is repo-wide, so it asks the person at the terminal to confirm and types nothing by itself. An unattended run refuses; pass `--yes` only when the user asked for the full pass, as [validate](../tests/validate.py) does.

The runner executes these checks:

- `layout.py`: component/config ownership, install roots, folder naming, high-level file placement, and batch references.
- `docs.py`: Markdown placement, roles, budgets, basename casing, links and model-name policy.
- `ruff check`: the configured lint set, including the [McCabe limit](../../.agents/CODE.md).
- `model_references.py`: catalog IDs, workflow defaults, and AudioCpp runtime IDs/paths.
- `frontend_wiring.py`: front-end wiring: HTML/JS asset paths, DOM element ids and injected settings keys.
- `basedpyright`: Python type errors.
- `inventory_code.py`: folder counts, sparse-folder warnings, merge candidates, module counts, file lines and function size; the gate is ruff's McCabe rule. Low counts prompt review, not findings.
- `typography.py`: ASCII punctuation only: em and en dashes, curly quotes, the ellipsis and no-break spaces are rejected in every tracked text file, quoted corpus references excepted. The pre-commit hook runs it on staged files.
- `comments.py`: markers, banner rules and commented-out code are rejected; comments that explain why stay.
- `spellings.py`: British spellings report the American form.
- `network_timeouts.py`: every HTTP call passes `timeout=`; the ASR upload wrapper owns its own.
- `overlay_access.py`: only `config/local_overlay.py` resolves overlay paths; a direct read elsewhere fails.

Reports go to `scripts/state/generated/shared/code_review/<run>/`. Complexity is gated by ruff at the limit in [code rules](../../.agents/CODE.md); the inventory lists the largest functions and excludes generated output, caches, model data, installs and trash.

## Duplicate check

The optional embedding check and its code mode: [similarity](SIMILARITY.md). Front-end wiring: [frontend
wiring](FRONTEND-WIRING.md). Both are part of the gate above.

Each check runs alone, for example `python -m scripts.review.layout`. `docs --words` prints every document by word count with its budget, `--roles` counts documents per role, and `--links` reports pointers, repeats and unlinked documents. A link fails when it is absolute, uses a backslash, carries a space without angle brackets, points into an untracked path, or misses its target or heading; repeats are advisory. Add `--tests` to run the model-free suite after the gate. Document organization lives in [NOTES-CONVENTIONS](../../.agents/NOTES-CONVENTIONS.md).

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

Format the whole repository with `scripts/review/format_py.bat`. Lint and format share one scope: repository root, Python files only, with `.venv`, `frameworks`, `data`, `trash`, `scripts/state`, run outputs and generated `ids.py` excluded. The gate compares formatting too; `--no-format-check` skips it. Tool inventory: [TOOLS.md](TOOLS.md).
