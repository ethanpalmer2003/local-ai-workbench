# Repository review

Run the complete review from `C:/AI`:

```powershell
python -m scripts.review
C:/AI/scripts/review/check_repo.bat
```

The default run is scoped to what changed since upstream. `--all` checks every section in about a minute, so it never asks; the runs that ask for agreement are the ones expected to pass five minutes, through [consent](../shared/consent.py).

The runner executes these checks:

- `layout.py`: component/config ownership, install roots, folder naming, high-level file placement, and batch references.
- `owned_tokens.py`: a literal one module owns may not be spelled in another, so a copied rule fails here instead of drifting; `--list` prints the table.
- `duplicates.py`: pylint's verbatim duplicate blocks against a reviewed baseline, so a new pasted block fails while the known ones do not; opt-in because pylint needs about a minute over `scripts`.
- `docs.py`: Markdown placement, roles, budgets, basename casing, links and model-name policy.
- `ruff check`: the configured lint set, including the [McCabe limit](../../.agents/CODE.md).
- `model_references.py`: catalog IDs, workflow defaults, and AudioCpp runtime IDs/paths.
- `frontend_wiring.py`: front-end wiring: HTML/JS asset paths, DOM element ids and injected settings keys.
- `basedpyright`: Python type errors.
- `inventory_code.py`: folder counts, sparse-folder warnings, merge candidates, module counts and file lines; low counts prompt review, not findings.
- `typography.py`: ASCII punctuation only: em and en dashes, curly quotes, the ellipsis and no-break spaces are rejected in every tracked text file, quoted corpus references excepted. The pre-commit hook runs it on staged files.
- `comments.py`: markers, banner rules and commented-out code are rejected; comments that explain why stay.
- `spellings.py`: British spellings report the American form.
- `dead_code.py`: an unused function or class, and unreachable code, through vulture; protocol
  attributes, method overrides and exported catalog constants are read outside the scan and stay out
  of the report ([libraries](LIBRARIES.md)).
- `package_audit.py` with deptry: the lock against `pyproject.toml`, installed-package advisories, and
  every import declared while every declaration is imported.
- `network_timeouts.py`: every HTTP call passes `timeout=`; the ASR upload wrapper owns its own.
- `overlay_access.py`: only `config/local_overlay.py` resolves overlay paths; a direct read elsewhere fails.

Reports go to `scripts/state/generated/shared/code_review/<run>/`. The inventory lists the largest functions and excludes generated output, caches, model data, installs and trash. Which checks run through a tool and which are this repository's own policy: [libraries](LIBRARIES.md).

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

Format what changed with `scripts/review/format_py.bat`; `--all` formats the whole repository. Lint and format share one scope: repository root, Python files only, with `.venv`, `frameworks`, `data`, `trash`, `scripts/state`, run outputs and generated `ids.py` excluded. The gate compares formatting too and follows the same scoping; `--no-format-check` skips it. Tool inventory: [TOOLS.md](TOOLS.md).
