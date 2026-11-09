# Checks

## Environment

- Interpreter `C:/AI/scripts/.venv/Scripts/python.exe`; use uv, never pip. If the user uv cache is restricted, set `UV_CACHE_DIR=C:/AI/scripts/state/cache/shared/uv`.
- Dependencies are declared in `pyproject.toml`, locked in `uv.lock`; CPU torch/torchaudio use the PyTorch CPU index; package changes need approval.

## Commands

- `python -m scripts.review.layout` checks structure; `python -m scripts.review.docs` checks documents.
- `basedpyright --level error` catches type/name contracts; syntax compilation alone is not enough. Run from `C:/AI` with the project environment and a normal-token invocation, or dependency discovery reports false missing imports.
- `python -m scripts.review` or `scripts/review/check_repo.bat` adds types, inventory, formatting and spelling.
- Import smoke checks must not start a suite, model, GPU workload or service.

## When

- Iterate with the failing module. Ask before the full review or the model-free suite; skip type checks after documentation-only edits. Levels and durations: [tool inventory](../scripts/review/TOOLS.md#levels).
- Prove a live configuration in seconds first: paths, ports, mode flags, one short request. A misconfiguration must fail immediately, not after a multi-minute timeout.
- Slow speech tests (Qwen3-TTS, Chatterbox, Sesame CSM) run in a console that stays open, through `launch_module(..., mode=SPLIT_INDEPENDENT)`; quick ones (Kokoro, Edge TTS) run inline. Wait for the user before another slow test.
- GPU metrics are sampled lower bounds; missing PIDs or counters are not zero.
- Performance runners use `BenchmarkLifecycle`, separating setup/load/warmup/cleanup and ranking only completed resident requests. Owner: [benchmark contract](../scripts/benchmarks/README.md).

## Review

- Read the latest [checkpoint](../notes/reviews/README.md); focus on changed contracts.
- Trace startup, readiness, requests, cleanup and process ownership; check error propagation and external API contracts.
- Check component keys, directory roles/types and config prefixes against [folder rules](FOLDERS.md); judge sparse-folder audit findings by ownership.
- Check a move or rename against [folder rules](FOLDERS.md); preserve sessions, shared assets and evidence.
- `scripts/review/frontend_wiring.py` checks asset paths, DOM ids and injected settings keys.
- Report findings, checks run and remaining limits.
