# Benchmark review status

The [shared lifecycle](../../scripts/benchmarks/README.md) separates
startup/loading/warmup/requests/cleanup. Only completed resident requests rank;
unobservable loading stays combined or null. Cold-process and dynamic-loading
workflow diagnostics remain separate. Different artifact/timing boundaries do
not establish a universal leaderboard.

The [coverage ledger](../../scripts/benchmarks/asr/shared/coverage.py) exposes
unsupported, manual and pending ASR adapters. Live pacing, first partials and
multilingual/noisy quality remain incomplete. `python -m scripts.benchmarks.audit_timing`
exposes timed-source scopes. [TODO](../TODO.md) owns pending work;
[test status](../../scripts/tests/notes/STATUS.md) owns run evidence.
