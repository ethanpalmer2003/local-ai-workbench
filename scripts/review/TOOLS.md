# Code validation tooling

What runs today. Use it to compare against other projects' stacks.

## Entry points

| Command | Covers |
| --- | --- |
| `python -m scripts.review` | structure/docs, model references, front-end wiring, types, inventory/complexity, formatting, spelling, dependency advisories |
| `... --prune` | installed packages outside the import graph, with the uninstall command |
| `scripts/review/check_repo.bat` | the same, from a normal terminal |
| `scripts/review/format_py.bat` | applies `ruff format` |
| `python -m scripts.tests.run` | regression suite through pytest, timings and reports |
| ... with `AI_MODEL_CHECKS=1` | adds asset/model checks kept out of regressions |
| `pre-commit run --all-files` | ruff lint and format, codespell |
| `python -m scripts.review.public_audit [--history]` | publish gate |
| `python -m scripts.review --scrub` | tree and history scan for personal terms before publishing |
| `python -m scripts.benchmarks.audit_timing` | benchmark timing-contract inventory (printed, not gated) |
| `python -m coverage run -m scripts.tests.run` | line coverage, then `coverage report` |

## Owners

| Tool | Owns |
| --- | --- |
| ruff lint | `[tool.ruff.lint]`: `E4 E7 E9 F UP C4 SIM I S C90 PT RET N RUF100`, line length 120, py313 |
| ruff format | `[tool.ruff.format]`; generated `ids.py` excluded |
| basedpyright | type errors, `--level error`, no strict mode |
| pytest | regression execution, timings, failure details |
| `structure_docs.py` | doc budgets, links, anchors, markdown hygiene, root placement, component keys, naming, folder rules, batch references |
| `model_references.py` | catalog ids, workflow defaults, AudioCpp runtime ids/paths |
| `frontend_wiring.py` | HTML/JS asset targets resolve, queried DOM ids exist, injected settings keys are both emitted and provided |
| `inventory_code.py` | inventory, file/function size, complexity depth, duplicate bodies, inline suppressions; `--complexity-debt` regenerates `COMPLEXITY-DEBT.md` |
| `public_audit.py` | secrets, credentials, home/machine paths, private words/inputs, large files, ignored-but-tracked |
| `audit_timing.py` | which benchmark runners use the shared timing contract |
| `dependencies.py` | installed packages the import graph never reaches; `--prune [--remove]`; `uv lock --check` |
| `coverage.py`, `pip-audit` | coverage; advisories run inside the gate (network, unreachable feed is a warning) |

Both ruff modes cover the repository root, `*.py`/`*.pyi` only, excluding `.venv`, `frameworks`, `data`, `trash`, `scripts/state`, run outputs and `ids.py`. Markdown and batch files are covered by `structure_docs.py`, HTML/JS by `frontend_wiring.py`; codespell reads tracked Python and Markdown.

Lint gates at McCabe 10. Anything above it must carry `# noqa: C901` and appear in `COMPLEXITY-DEBT.md`; the table is currently empty, so the gate is fully enforced. `S101` is ignored under `scripts/tests`; `S603/S606/S607/S310` repo-wide because known local executables and curated URLs are intended.

## Deliberately absent

- Mutation testing.
- Dead-code and duplicate-code detectors: `inventory_code.py` covers function bodies only.
- Standalone `bandit`/`semgrep`; ruff `S` covers the common cases.
- Markdown formatting; `structure_docs.py` enforces links, budgets, anchors and hygiene, and the doc tables are generated.
- Import-boundary linting; layering is convention.
- JS/TS tooling and a CI server; everything runs locally.
