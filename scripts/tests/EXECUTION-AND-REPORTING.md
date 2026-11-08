# Execution and reporting conventions

Companion to the [test suite index](README.md); it holds the execution rules, evidence conventions and report/status categories for the tests here.

## Execution and evidence

- `test_model_free.bat` combines mocked unit tests, loopback/subprocess integration and local-asset checks. Unmarked process starts and framework DLL loads are blocked; this is not a security sandbox. The VRAM entry points are separate: `test_live_launchers.bat` runs the user-facing launchers/proxies (including the saved-PCM practice gateway), `test_live_backends.bat` runs the direct per-engine probes, and `test_live_all.bat` runs both. The target sets are disjoint; both report the same `results.json`/`report.json` shape and refuse to stop an existing user session. Native runs show a per-target progress bar, join the kill-on-close job, and assign every spawned worker/probe to it; closing the test terminal ends everything the run started. Component folders stay shared; entry points select the mode. Failures persist to each run's `artifacts/unittest.txt` and `report.json` `results`.
- Extend shared fixtures/contracts before duplicating setup. Keep imports inert and scenario assertions local; a regression failure never enables live inference automatically. Owner: [fixture guide](shared/FIXTURES.md).
- Benchmark ranking rules live with the [benchmark lifecycle](../benchmarks/README.md). Only completed resident requests qualify for standardized rankings; cold probes are diagnostics.

- Respect explicit deferrals. A guide or saved result never authorizes inference, package changes, persistent services or a long run.
- Use approved normal-token execution for native benchmarks; record AppContainer/admin flags separately. Reuse matching healthy services; never stop unrelated sessions.
- Record warmup/startup separately, identical inputs/settings, order, sample count, reasoning, seeds, model hashes, execution context, failures and cleanup.
- Shared GPU monitor saves baseline/process/stage samples when available; sampled peaks are lower bounds, missing counters are null/unavailable.
- Benchmark default reasoning: low; normal launch/live smoke: medium. Older xhigh/mixed runs do not establish a medium ranking.
- Model-performance tasks use English/code. Unicode fixtures remain valid correctness tests; language-practice ASR has its own explicitly requested multilingual scope.
- Repository review reports folder item counts and Python/Markdown line counts; its Python function audit excludes tests and uses limits of depth 4 and 100 code lines/function. A size finding is distinct from a type failure.

## Reports and context categories

- `verified`, `no-gain`, `inconclusive`, `superseded`, `unreviewed`; new runs default unreviewed. Retain partial/failed evidence.
- Poll compact summaries/status at reasonable intervals; detailed traces stay in artifacts. Do not rerun successful checks without a new reason.
- [Status](notes/STATUS.md), [outcomes](notes/OUTCOMES.md), [estimates](notes/ESTIMATES.md), [pending work](../../notes/TODO.md).
