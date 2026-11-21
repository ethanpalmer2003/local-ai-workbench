# HRX experimental backend

- Select `--llama-cpp-build hrx` when starting the API proxy module (`python -m scripts.launchers.llamacpp.llamacpp_proxy --llama-cpp-build hrx`). Runtime: `frameworks/llamacpp/additions/hrx/runtime`.
- Lemonade remains the normal default; HRX uses its matching Swift profile. Preserve installed native paths and retained rollback packages.

## Latest local evidence

- 2026-10-15 source heads: llama.cpp `4dfa7b2`, HRX `bf1d3963e`, ROCr `65d961f109`, with Windows fixes.
- GPU discovery, six CPU-reference operators, normal/chunk-size-3 tensors, exact code tokens/text, chat and installation hashes passed. Short decode: 14.74/15.92 tok/s, 8K/f16 KV/no speculation. Validation (../../tests/output/probes/hrx_updates/verified/20261015-rebuild/artifacts/report.md).
- Matched previous/current 64-token screen: aggregate 13.62 versus 13.92 tok/s (+2.2%); variation exceeded the difference, so no demonstrated decode speedup. Comparison (../../tests/output/probes/hrx_performance/unreviewed/1792112820577230300/artifacts/report.json).
- Larger contexts/other models remain unverified. Merged prefill/router changes do not establish benefits for this dense IQ3_XXS decode workload.
- 2026-11-21: no retained patch applies to the current upstream heads (llama.cpp `76c3785b9`, HRX `b81ff778b`, rocm-systems `0ca1de96e9`). `tests/test-hrx-ops.cpp` no longer exists, and upstream has since landed IQ3_XXS skinny-matmul decoding (#200) and routed expert pairs (#175), the subject of two of them. The patch set and checkpoints describe the 2026-10-15 stack only; a fresh start would clone and fix forward instead of re-merging them.

## Diagnosis retained

- Earlier codebook/fusion routing blockers were fixed. Initial incorrect fast routing broke chunked prefill and was rejected; corrected F32 output handling restored the intended path.
- Current-speed CPU attribution is about 15.42%, superseding the old 2.8% figure. Old 2.6 tok/s diagnostics are not current performance.
- Native Windows profiling has coverage/tooling limits; host scheduler timings are not GPU kernel attribution. Q2_K GPU matmul and further register/kernel analysis remain pending.

## Maintenance

- [Merge/build/validate/install/restore commands](../../download/frameworks/UPDATES.md#hrx).
- Saved local work: patches in [hrx-patches](hrx-patches/README.md), full source snapshots and the verified pointer in `state/llamacpp/hrx`, local commits on `codex/*` branches in the checkouts, and the 2026-10-15 checkpoint under `tests/output/probes/hrx_updates/verified/`.
- Source/checkpoints: `frameworks/llamacpp/additions/hrx`; current state/pointers/patches: `state/llamacpp/hrx`.
- Modified checkouts/local commits require reviewed merges. New builds/native tests need explicit scope and long-run approval; preserve the working runtime on failure.
- Upstream/vendor availability differs from this custom Windows installation. Check actual support before treating a release as interchangeable.
- [Pending work](../../../notes/TODO.md), [historical outcomes](../../tests/notes/OUTCOMES.md).
