# HRX experimental backend

- Select `--llama-cpp-build hrx` when starting the API proxy module (`python -m scripts.launchers.llamacpp.llamacpp_proxy --llama-cpp-build hrx`). Runtime: `frameworks/llamacpp/additions/hrx/runtime`.
- Lemonade remains the normal default; HRX uses its matching Swift profile. Preserve installed native paths and retained rollback packages.

## Latest local evidence

- 2026-10-15 source heads: llama.cpp `4dfa7b2`, HRX `bf1d3963e`, ROCr `65d961f109`, with Windows fixes. This is the last pair known to build.
- GPU discovery, six CPU-reference operators, normal/chunk-size-3 tensors, exact code tokens/text, chat and installation hashes passed. Short decode: 14.74/15.92 tok/s, 8K/f16 KV/no speculation. Validation (../../runs/tests/probes/hrx_updates/verified/20261015-rebuild/artifacts/report.md).
- Matched previous/current 64-token screen: aggregate 13.62 versus 13.92 tok/s (+2.2%); variation exceeded the difference, so no demonstrated decode speedup. Comparison (../../runs/tests/probes/hrx_performance/unreviewed/1792112820577230300/artifacts/report.json).
- Larger contexts/other models remain unverified. Merged prefill/router changes do not establish benefits for this dense IQ3_XXS decode workload.
- 2026-11-21: no retained patch applies to the current heads. `tests/test-hrx-ops.cpp` is gone, and upstream landed IQ3_XXS skinny-matmul decoding (#200) and routed expert pairs (#175), the subject of two of them, so the patch set describes the 2026-10-15 stack only.
- 2026-11-21 merge and build: all three checkouts moved cleanly to llama.cpp `3e71ba3ff`, HRX `b6ad3f37e` and rocm-systems `6ac2f27c18`. Build prerequisites are now owned by code and here: `wkmi.lib` is a DVC pointer fetched anonymously from `s3://therock-dvc/rocm-systems`; ROCr needs `Clang_DIR`/`LLVM_DIR` from `data/ROCm/therock-dist-windows-gfx110X-all-10.2.0a20260927/lib/llvm/lib/cmake`; HRX needs `AMDF_BUILD`, `IREE_ROCM_PATH` and the current venv's Python, which `hrx/build.py` passes; llama.cpp needs `hrx_DIR`, `loomc_DIR` and [packages.cmake](../../download/frameworks/llamacpp/hrx/packages.cmake), since its test targets link `hrx::hrx` from a sibling directory.
- 2026-11-21 latest stack: llama.cpp `llama-server`, `llama-cli` and `test-backend-ops` now build against `hrx-system` `b6ad3f37e`. That needed one registered patch, `llamacpp-hrx-api-port`: every transfer call moves to its `_linear` form and every stream wait passes `HRX_WAIT_FLAG_NONE`, plus the `std::array` bound written out because MSVC rejects a captured `constexpr` (C2975). The UI asset check is avoided by configuring with `LLAMA_BUILD_UI=OFF` and `LLAMA_USE_PREBUILT_UI=OFF`, and the candidate reuses the installed `hrx-tensor-probe.exe` because its `.cpp` source is not in this repository.
- 2026-11-21 open blocker: the staged candidate runs, but `hrx-info` reports `amdgpu: 0 devices` with either the new or the installed `hsa-runtime64.dll`, under `ROCR_VISIBLE_DEVICES=1`, `0` or none, so device enumeration stopped working independently of the build. Nothing installs until a device appears.
- Local fixes live in [fixes](../../download/frameworks/llamacpp/hrx/fixes/fixes.json): `python -m scripts.download.frameworks.llamacpp.hrx.fixes` reports `applied`, `needed` or `drifted` per fix, and `--apply` reapplies them.

## Diagnosis retained

- Earlier codebook/fusion routing blockers were fixed; initial fast routing broke chunked prefill and was rejected.
- Current-speed CPU attribution is about 15.42%, superseding the old 2.8% figure. Old 2.6 tok/s diagnostics are not current performance.
- Native Windows profiling has coverage/tooling limits; host scheduler timings are not GPU kernel attribution.

## Maintenance

- [Merge/build/validate/install/restore commands](../../download/frameworks/UPDATES.md#hrx).
- Saved local work: [hrx-patches](hrx-patches/README.md), the [fix registry](../../download/frameworks/llamacpp/hrx/fixes/fixes.json), snapshots and the verified pointer in `state/llamacpp/hrx`, the local-only commits as git bundles in [the framework's local-work folder](../../download/frameworks/llamacpp/hrx/local-work/README.md), and the `codex/*` branches.
- Modified checkouts/local commits require reviewed merges. New builds need explicit scope and long-run approval; preserve the working runtime on failure.
- Upstream/vendor availability differs from this custom Windows installation. Check actual support before treating a release as interchangeable.
- [Pending work](../../../notes/TODO.md), [historical outcomes](../../tests/notes/OUTCOMES.md).
