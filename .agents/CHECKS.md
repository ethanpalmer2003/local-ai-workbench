# Checks

## Environment

- Interpreter `C:/AI/scripts/.venv/Scripts/python.exe`; use uv, never pip. If the user uv cache is restricted, set `UV_CACHE_DIR=C:/AI/scripts/state/cache/shared/uv`.
- Dependencies `scripts/requirements.txt`; CPU torch/torchaudio use the PyTorch CPU index; package changes need approval.

## Commands

- `python -m scripts.review.structure` checks keys, paths, imports, links and Markdown budgets.
- `basedpyright --level error` catches type/name contracts; syntax compilation alone is not enough. Run from `C:/AI` with the project environment and a normal-token invocation, or dependency discovery reports false missing imports.
- `python -m scripts.review` or `scripts/review/check.bat` adds types, inventory and the depth/length audit. Existing audit findings stay visible and are not type failures.
- Import smoke checks must not start a suite, model, GPU workload or service.

## When

- Iterate with the failing module; run the model-free suite once at the end. Skip type checks after documentation-only edits.
- Prove a live configuration in seconds first: paths, ports, mode flags, one short request. A misconfiguration must fail immediately, not after a multi-minute timeout.
- GPU metrics are sampled lower bounds; missing PIDs or counters are not zero.
- Performance runners use `BenchmarkLifecycle`, separating setup/load/warmup/cleanup and ranking only completed resident requests. Owner: [benchmark contract](../scripts/benchmarks/README.md).

## Review

- Read the latest [checkpoint](../notes/reviews/README.md); focus on changed contracts.
- Trace startup, readiness, requests, cleanup and process ownership; check error propagation and external API contracts.
- Check component keys, directory roles/types and config prefixes against [folder rules](FOLDERS.md); judge sparse-folder audit findings by ownership.
- Follow a moved path through imports, catalogs, native settings, batches, UI/assets and docs; preserve sessions, shared assets and evidence.
- `scripts/review/frontend.py` checks asset paths, DOM ids and injected settings keys.
- Report findings, checks run and remaining limits.
