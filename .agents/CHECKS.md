# Checks

## Environment

- Interpreter `C:/AI/.venv/Scripts/python.exe`. If the uv cache is restricted, set `UV_CACHE_DIR=C:/AI/scripts/state/cache/shared/uv`.
- Dependencies are declared in `pyproject.toml` and locked in `uv.lock`; CPU torch/torchaudio use the PyTorch CPU index.

## Commands

- `python -m scripts.review.checks.layout` checks structure; `.docs` documents; `.comments` rejects markers, banner rules and commented-out code.
- `basedpyright --level error` catches type/name contracts; syntax compilation alone is not enough. Run from `C:/AI` with the project environment and a normal-token invocation, or dependency discovery reports false missing imports.
- `python -m scripts.review` or `scripts/review/check_repo.bat` runs every static check; `--tests` adds the suite.
- Import smoke checks must not start a suite, model, GPU workload or service.

## When

- A commit checks what it is recording: `--commit` reads the working tree against `HEAD`, so earlier unpushed commits do not run again. The scoped gate and scoped suite follow ruff, codespell and the punctuation pass. About fifteen seconds for a code change, seconds for prose.
- A push checks everything: `--push` runs every section and every class when the unpushed commits touch Python, and the prose sections with no class when they do not; no Python behavior changed, and the last push was green.
- Both commands also run by hand; there is no separate edit stage.
- The suite is a feedback loop: one import hop from the change by default. No Python path runs none, a comment or docstring edit runs none, and the manifests keep every class on a code change; the launcher and proxy block is in the set; see [selection](../scripts/tests/scoped_selection.py).
- The gate is scoped the same way: only the sections whose inputs changed, and the type check covers the changed modules plus their direct importers. A bare run adds the unpushed commits to the change set; `--commit` does not. `--fast` skips types, inventory, advisories and the package summary; an empty change set runs every section. Each section records its seconds under `scripts/state/logs/shared/review/`, so the cost of a check comes from history instead of a rerun.
- Live and measure work is scheduled from [TODO](../notes/TODO.md), never part of a code change. Levels: [tool inventory](../scripts/review/TOOLS.md#levels).
- Prove a live configuration in seconds first: paths, ports, mode flags, one short request. A misconfiguration must fail immediately.
- Slow speech tests (Qwen3-TTS, Chatterbox, Sesame CSM) run in a console that stays open, through `launch_module(..., mode=SPLIT_INDEPENDENT)`; quick ones run inline. Wait for the user before another slow test.
- GPU metrics are sampled lower bounds; missing PIDs or counters are not zero.
- Performance runners use `BenchmarkLifecycle`, separating setup/load/warmup/cleanup and ranking only completed resident requests. Owner: [benchmark contract](../scripts/benchmarks/README.md).

## Review

- Answer the ten [review questions](REVIEW.md) against the change; they are the checklist this section used to describe.
- Read the latest [checkpoint](../notes/reviews/README.md); focus on changed contracts.
- Trace startup, readiness, requests, cleanup and process ownership; check error propagation.
- Check component keys, directory roles/types and config prefixes against [folder rules](FOLDERS.md); judge sparse-folder audit findings by ownership.
- `scripts/review/checks/frontend_wiring.py` checks asset paths, DOM ids and injected settings keys.
- Report findings, checks run and remaining limits.
