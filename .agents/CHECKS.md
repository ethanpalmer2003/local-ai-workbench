# Checks

## Environment

- Interpreter `C:/AI/.venv/Scripts/python.exe`. If the uv cache is restricted, set `UV_CACHE_DIR=C:/AI/scripts/state/cache/shared/uv`.
- Dependencies are declared in `pyproject.toml`, locked in `uv.lock`; CPU torch/torchaudio use the PyTorch CPU index; package changes need approval.

## Commands

- `python -m scripts.review.checks.layout` checks structure; `.docs` documents; `.comments` rejects markers, banner rules and commented-out code.
- `basedpyright --level error` catches type/name contracts; syntax compilation alone is not enough. Run from `C:/AI` with the project environment and a normal-token invocation, or dependency discovery reports false missing imports.
- `python -m scripts.review` or `scripts/review/check_repo.bat` runs every static check: lint, types, inventory, docs, spelling, deps; `--tests` adds the suite.
- Import smoke checks must not start a suite, model, GPU workload or service.

## When

- An edit is the only check before a push: `python -m scripts.review` covers the sections and the types the change reaches, and the test module you touched covers the rest. About thirteen seconds for one Python file, two for a document.
- A commit only repairs: ruff check and format, codespell, the punctuation pass. Seconds.
- A push runs everything: `python -m scripts.review --all` and `python -m scripts.tests.run --all`. About a minute, and this is the only completeness guarantee.
- The suite is a feedback loop: by default one import hop from the change, `--all` at push for the rest. No Python path runs none, a comment or docstring edit runs none, and the manifests keep every class on a code change; the launcher and proxy block is in this set rather than outside it; see [selection](../scripts/tests/scoped_selection.py).
- The gate is scoped the same way: only the sections whose inputs changed since the upstream branch, working tree and unpushed commits alike, and the type check covers the changed modules plus their direct importers. `--fast` skips types, inventory, advisories and the package summary; `--all` runs every section, and so does an empty change set. Each section records its seconds under `scripts/state/logs/shared/review/`, so the cost of a check comes from history instead of a rerun.
- Live and measure work is scheduled from [TODO](../notes/TODO.md), never part of a code change. Levels: [tool inventory](../scripts/review/TOOLS.md#levels).
- Prove a live configuration in seconds first: paths, ports, mode flags, one short request. A misconfiguration must fail immediately, not after a multi-minute timeout.
- Slow speech tests (Qwen3-TTS, Chatterbox, Sesame CSM) run in a console that stays open, through `launch_module(..., mode=SPLIT_INDEPENDENT)`; quick ones (Kokoro, Edge TTS) run inline. Wait for the user before another slow test.
- GPU metrics are sampled lower bounds; missing PIDs or counters are not zero.
- Performance runners use `BenchmarkLifecycle`, separating setup/load/warmup/cleanup and ranking only completed resident requests. Owner: [benchmark contract](../scripts/benchmarks/README.md).

## Review

- Answer the ten [review questions](REVIEW.md) against the change; they are the checklist this section used to describe.
- Read the latest [checkpoint](../notes/reviews/README.md); focus on changed contracts.
- Trace startup, readiness, requests, cleanup and process ownership; check error propagation.
- Check component keys, directory roles/types and config prefixes against [folder rules](FOLDERS.md); judge sparse-folder audit findings by ownership.
- `scripts/review/checks/frontend_wiring.py` checks asset paths, DOM ids and injected settings keys.
- Report findings, checks run and remaining limits.
