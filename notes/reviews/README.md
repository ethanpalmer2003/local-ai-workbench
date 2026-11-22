# Code review status

Index only: it lists what has been reviewed and links the record that holds the evidence.

Current shared-runtime, fixture and naming contracts pass non-live validation.
This is a scoped checkpoint, not an exhaustive codebase audit.

| Area | Current status |
| --- | --- |
| [Structure](STRUCTURE-REVIEW.md) | Canonical paths and concise-doc guards active |
| [Benchmarks](BENCHMARK-MIGRATION.md) | Shared lifecycle active; coverage and comparable quality/resource measurements remain incomplete |
| [Runtime](RUNTIME-CONSOLIDATION.md) | Shared lifecycle, audio, uploads and native binding owners established |
| [Regressions](REGRESSION-FIXTURE-CONSOLIDATION.md) | Shared fixtures/contracts and explicit non-live/live boundary active |

Dated records, newest first: [self review pass 2](SELF-REVIEW-2026-11-22-PASS-2.md),
[self review](SELF-REVIEW-2026-11-22.md),
[heavyweight review triage](HEAVYWEIGHT-REVIEW-2026-11-21.md),
[ROCm driver timeout](ROCM-DRIVER-TIMEOUT-2026-11-13.md),
[embeddings](EMBEDDINGS-2026-11-10.md), [llama.cpp Vulkan](LLAMACPP-VULKAN-2026-11-09.md),
[Strata profiles](STRATA-PROFILES-2026-11-09.md), [ComfyUI video](COMFYUI-VIDEO-2026-11-09.md) and
[upstream Kokoro](UPSTREAM-KOKORO-2026-11-08.md).

Validation evidence belongs in [test status](../../scripts/tests/notes/STATUS-INDEX.md).
[TODO](../TODO.md) owns pending work. Procedures stay beside code; the
[review practice](../../.agents/CHECKS.md#review) owns review practice.
Keep these pages current-state only; do not append migration narratives or old checks.
