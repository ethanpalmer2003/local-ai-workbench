# Code validation tooling

What runs today, in one place. Use it to compare against other projects' stacks; nothing here is a wish list.

## Entry points

| Command | Covers |
| --- | --- |
| `python -m scripts.review` | structure, model drift, front-end wiring, types, inventory/complexity, formatting |
| `scripts/review/check.bat` | the same, from a normal terminal |
| `scripts/review/format.bat` | applies `ruff format` to the repository |
| `python -m scripts.tests.run` | regression suite, per-test timings, persisted reports |
| `python -m scripts.review.public_audit [--history]` | publish gate |

## Tools and their owners

| Tool | Owns | Notes |
| --- | --- | --- |
| ruff (lint) | `pyproject.toml` `[tool.ruff.lint]` | `E4 E7 E9 F UP C4 SIM I`, line length 120, target py313 |
| ruff (format) | `pyproject.toml` `[tool.ruff.format]` | enforced by the review gate; generated `ids.py` excluded |
| basedpyright | type errors | `--level error` only; no strict mode |
| `structure.py` | docs budgets, links, component keys, naming, folder rules | maintained files only |
| `model_drift.py` | catalog ids, workflow defaults, AudioCpp runtime ids/paths | - |
| `frontend.py` | asset paths, DOM ids, injected settings contracts | static, never executes pages |
| `inventory.py` | inventory, file/function size, complexity depth, duplicate bodies | complexity gates; tables advisory |
| `public_audit.py` | secrets, credentials, home/machine paths, private words, private inputs, large files, ignored-but-tracked | `--history` scans every commit |
| `unittest` runner | behaviour regressions | 501 tests, ~15 s, per-test timings and `report.md` |

Scope for both ruff modes: repository root, `*.py`/`*.pyi` only; `.venv`, `frameworks`, `data`, `trash`, `scripts/state`, run outputs and generated `ids.py` excluded. Other file types are covered by `structure.py` (Markdown) and `frontend.py` (HTML/JS).

## Deliberately absent

- Coverage measurement, mutation testing.
- Dead-code and duplicate-code detectors (`vulture`, `jscpd`) - `audit.py` covers only function bodies.
- Security scanning (`bandit`, `semgrep`) and dependency auditing (`pip-audit`, lockfile checks).
- `pre-commit` hooks; the gate is a command, not a hook.
- Markdown linting; `structure.py` enforces only links, budgets and naming.
- Import-boundary enforcement (`import-linter`); layering is convention, not checked.
- JS/TS tooling: no ESLint, no TypeScript check for the pages.
- Spell/grammar checking.
