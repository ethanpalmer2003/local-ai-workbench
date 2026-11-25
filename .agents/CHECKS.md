# Checks

## Environment

- Interpreter `C:/AI/.venv/Scripts/python.exe`; a restricted uv cache needs `UV_CACHE_DIR=C:/AI/scripts/state/cache/shared/uv`.
- Dependencies are declared in `pyproject.toml` and locked in `uv.lock`; CPU torch/torchaudio use the PyTorch CPU index.

## Commands

- `python -m scripts.review.checks.layout` checks structure; `.docs` documents; `.comments` rejects markers, banners and commented-out code; `.expression` rejects a condition nesting operators three levels deep.
- `basedpyright --level error` catches type/name contracts; syntax compilation alone is not enough. Run from `C:/AI` with the project environment and a normal-token invocation, or dependency discovery reports false missing imports.
- `python -m scripts.review` or `scripts/review/check_repo.bat` runs every static check; `--tests` adds the suite.
- An import smoke check starts no suite, model, GPU or service.

## When

- A commit checks what it is recording: `--commit` reads the working tree against `HEAD`, so earlier unpushed commits do not run again. The scoped gate and scoped suite follow ruff, codespell and the punctuation pass. About five seconds for a code change, seconds for prose.
- A push checks everything: `--push` runs every section and every class when the unpushed commits touch Python, and the prose sections with no class when they do not; no Python behavior changed, and the last push was green.
- By hand both need `--manual`; hooks pass their stage. Single files and sections are exempt; there is no separate edit stage.
- The suite is a feedback loop: one import hop from the change. No Python path runs none; comments and docstrings too, and the three manifest files ([registry](../scripts/tests/registry.py), runner, selection) keep every class.
- The gate is scoped the same way; the type check covers the changed modules plus their direct importers. `--commit` reads the working tree, `--push` and `--manual` add unpushed commits, and an empty set runs every section. `--fast` skips types, inventory, advisories and the package summary. Each section records its seconds under `scripts/state/logs/shared/review/`.
- Staleness has one owner per question: which files to read and what moved since upstream is [file sets](../scripts/shared/file_sets.py), git only; whether inputs still match a recorded run is [staleness](../scripts/shared/staleness.py), content only, backing the live-suite stamps and the validation cache; evidence age is an age rule beside the evidence.
- Live and measure work is scheduled from [TODO](../notes/TODO.md), never part of a code change. Levels: [tool inventory](../scripts/review/TOOLS.md#levels).
- Prove a live configuration in seconds first: paths, ports, mode flags, one short request. A misconfiguration must fail immediately.
- Slow speech tests run in a console that stays open (`launch_module(..., mode=SPLIT_INDEPENDENT)`); wait for the user before another.
- GPU metrics are sampled lower bounds; missing PIDs or counters are not zero.
- Performance runners use `BenchmarkLifecycle`, separating setup/load/warmup/cleanup and ranking only completed resident requests. Owner: [benchmark contract](../scripts/benchmarks/README.md).

## Review

- Answer the ten [review questions](REVIEW.md) against the change; they are the checklist this section used to describe.
- Read the latest [checkpoint](../notes/reviews/README.md); focus on changed contracts.
- Trace startup, readiness, requests, cleanup and process ownership; check error propagation.
- Check component keys, directory roles/types and config prefixes against [folder rules](FOLDERS.md); judge sparse-folder audit findings by ownership.
- Report findings, checks run and remaining limits.
