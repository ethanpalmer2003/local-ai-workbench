# Shared test cases

Tests whose subject is not one engine: repository tools, config and benchmark contracts, and the
cross-component runtime rules. Engine areas keep their own folder, the gate its own
[review cases](../review/README.md), and the runners their [suite entry points](../suites/README.md).

- Flat cases cover the tools: model admin, toolchains, capability matrix, bat launchers, workspace
  integrity, Strata profiles, inputs overlay, validate, preflight, stage runner and ROCm inventory.
- Grouped subfolders: `runtime/` (sessions, residency, resources), `models/` (catalog, sync, languages),
  `benchmarks/` and `reports/` (measurement and report contracts), `workflows/` (ComfyUI graphs),
  `regression/` (suite boundaries).
- Fixtures live in [tests/shared](../../shared/FIXTURES.md); execution and artifact rules:
  [test guide](../../README.md). Run everything with `python -m scripts.tests.run`.
