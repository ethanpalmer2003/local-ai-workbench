# Code review status

Current shared-runtime, fixture and naming contracts pass non-live validation.
This is a scoped checkpoint, not an exhaustive codebase audit.

| Area | Current status |
| --- | --- |
| [Structure](STRUCTURE-REVIEW.md) | Canonical paths and concise-doc guards active |
| [Benchmarks](BENCHMARK-MIGRATION.md) | Shared lifecycle active; coverage and comparable quality/resource measurements remain incomplete |
| [Runtime](RUNTIME-CONSOLIDATION.md) | Shared lifecycle, audio, uploads and native binding owners established |
| [Regressions](REGRESSION-FIXTURE-CONSOLIDATION.md) | Shared fixtures/contracts and explicit non-live/live boundary active |

Validation evidence belongs in [test status](../../scripts/tests/notes/STATUS.md).
[TODO](../TODO.md) owns pending work. Procedures stay beside code; the
[review practice](../../.agents/CHECKS.md#review) owns review practice.
Keep these pages current-state only; do not append migration narratives or old checks.
