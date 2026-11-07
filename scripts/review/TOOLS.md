# Code validation tooling

What runs today. Use it to compare against other projects' stacks.

## Entry points

| Command | Covers |
| --- | --- |
| `python -m scripts.review` | structure/docs, model references, front-end wiring, types, inventory/complexity, formatting |
| `scripts/review/check_repo.bat` | the same, from a normal terminal |
| `scripts/review/format_py.bat` | applies `ruff format` |
| `python -m scripts.tests.run` | regression suite through pytest, timings and reports |
| ... with `AI_MODEL_CHECKS=1` | adds asset/model checks kept out of regressions |
| `pre-commit run --all-files` | ruff lint and format; codespell is manual |
| `python -m scripts.review.public_audit [--history]` | publish gate |
| `python -m scripts.benchmarks.audit_timing` | benchmark timing-contract audit |
| `python -m coverage run -m scripts.tests.run` | line coverage, then `coverage report` |
| `python -m pip_audit -r scripts/requirements.txt` | dependency advisories (network) |

## Owners

| Tool | Owns |
| --- | --- |
| ruff lint | `[tool.ruff.lint]`: `E4 E7 E9 F UP C4 SIM I S C90`, line length 120, py313 |
| ruff format | `[tool.ruff.format]`; generated `ids.py` excluded |
| basedpyright | type errors, `--level error`, no strict mode |
| pytest | regression execution, timings, failure details |
| `structure_docs.py` | doc budgets, links, component keys, naming, folder rules |
| `model_references.py` | catalog ids, workflow defaults, AudioCpp runtime ids/paths |
| `frontend_wiring.py` | asset paths, DOM ids, injected settings contracts |
| `inventory_code.py` | inventory, file/function size, complexity depth, duplicate bodies |
| `public_audit.py` | secrets, credentials, home/machine paths, private words/inputs, large files, ignored-but-tracked |
| `audit_timing.py` | every benchmark runner uses the shared timing contract |
| `coverage.py`, `pip-audit`, `codespell` | coverage, dependency advisories, spelling (manual hook) |

Both ruff modes cover the repository root, `*.py`/`*.pyi` only, excluding `.venv`, `frameworks`, `data`, `trash`, `scripts/state`, run outputs and `ids.py`. Markdown is covered by `structure_docs.py`, HTML/JS by `frontend_wiring.py`.

Lint gates at McCabe 20; the five dispatchers above it carry `# noqa: C901`. `S101` is ignored under `scripts/tests`; `S603/S606/S607/S310` repo-wide because known local executables and curated URLs are intended.

## Deliberately absent

- Mutation testing.
- Dead-code and duplicate-code detectors - `inventory_code.py` covers function bodies only.
- Standalone `bandit`/`semgrep`; ruff `S` covers the common cases.
- Markdown linting; `structure_docs.py` enforces links, budgets and naming.
- Import-boundary linting; layering is convention.
- JS/TS tooling and a CI server; everything runs locally.
