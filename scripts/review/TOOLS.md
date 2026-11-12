# Code validation tooling

What runs today. Use it to compare against other projects' stacks.

## Levels

Measured on this machine; only the last two open a model or service. When to run which is [checks policy](../../.agents/CHECKS.md).

| Level | Scope | Typical time |
| --- | --- | --- |
| edit | staged-file hooks: ruff, codespell, ASCII punctuation | seconds |
| module | one `scripts.review.*` check: docs, layout, wiring, typography, model references | under 2 s |
| gate | `python -m scripts.review`: adds lint, types, inventory, formatting, spelling, deps | about 45 s |
| suite | `python -m scripts.review --tests`, model-free | about 75 s total |
| live | `bat/tests/test_live_launchers.bat`, `test_live_backends.bat` | minutes |
| measure | a benchmark runner | minutes to hours |
| publish | `public_audit --history` and `--scrub` | seconds to a minute |

## Entry points

| Command | Covers |
| --- | --- |
| `python -m scripts.review` | layout, docs, model references, front-end wiring, lint, types, inventory, formatting, spelling, advisories, deptry, lock and leftovers |
| ... --tests | the same, then the model-free test suite |
| `... --prune` | installed packages nothing imports or declares, with the uninstall command |
| `scripts/review/check_repo.bat` | the same, from a normal terminal |
| `scripts/review/format_py.bat` | applies `ruff format` |
| `python -m scripts.tests.run` | regression suite through pytest, timings and reports |
| `python -m scripts.tests.validate` | updates frameworks, then gate, suite and both live suites in one progress bar; `--models` adds the source check; skips unchanged live stages |
| `python -m scripts.tools.stage_runner MODULE [ARGS...]` | wraps one long command in the same bar and keeps its output; `--stage-known KEY` takes the expected range from `stage_times` |
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
| `layout.py` | component keys, ownership, install roots, folder naming, batch references |
| `docs.py` | doc roles, budgets, links, anchors and model-name policy |
| `model_references.py` | catalog ids, workflow defaults, AudioCpp runtime ids/paths |
| [frontend wiring](FRONTEND-WIRING.md) | asset targets resolve, DOM ids exist, settings keys both emitted and provided |
| `inventory_code.py` | inventory, file/function size, inline suppressions; `--complexity-debt` regenerates `COMPLEXITY-DEBT.md` |
| `public_audit.py` | secrets, credentials, home/machine paths, vocabulary and input names, large files, ignored-but-tracked |
| `audit_timing.py` | which benchmark runners use the shared timing contract |
| `package_audit.py` | leftovers no import or manifest declares; `--prune [--remove]`; `uv lock --check` |
| `coverage.py`, `pip-audit` | coverage; advisories run inside the gate (network, unreachable feed is a warning) |

Both ruff modes cover the repository root, `*.py`/`*.pyi` only, excluding `.venv`, `frameworks`, `data`, `trash`, `scripts/state`, run outputs and `ids.py`. Codespell reads tracked Python and Markdown.

Lint gates at the [McCabe limit](../../.agents/CODE.md). Anything above it is listed in `COMPLEXITY-DEBT.md` and has to be split; the ledger is the only place debt is recorded. The table is currently empty. `S101` is ignored under `scripts/tests`; `S603/S606/S607/S310` repo-wide because known local executables and curated URLs are intended.

## Deliberately absent

- Mutation testing.
- Dead-code and duplicate-code detectors: `inventory_code.py` covers function bodies only.
- Standalone `bandit`/`semgrep`; ruff `S` covers the common cases.
- Markdown formatting; `docs.py` enforces links, budgets, anchors and hygiene, and the doc tables are generated.
- Import-boundary linting; layering is convention.
- JS/TS tooling and a CI server; everything runs locally.
