# HRX experimental backend

- Select `--llama-cpp-build hrx` when starting the API proxy module (`python -m scripts.launchers.llamacpp.llamacpp_proxy --llama-cpp-build hrx`). Runtime: `frameworks/llamacpp/additions/hrx/runtime`.
- Lemonade remains the normal default; HRX uses its matching Swift profile. Preserve installed native paths and retained rollback packages.

## Latest local evidence

- 2026-10-15 source heads: llama.cpp `4dfa7b2`, HRX `bf1d3963e`, ROCr `65d961f109`, with Windows fixes.
- GPU discovery, six CPU-reference operators, normal/chunk-size-3 tensors, exact code tokens/text, chat and installation hashes passed. Short decode: 14.74/15.92 tok/s, 8K/f16 KV/no speculation. Validation (../../tests/output/probes/hrx_updates/verified/20261015-rebuild/artifacts/report.md).
- Matched previous/current 64-token screen: aggregate 13.62 versus 13.92 tok/s (+2.2%); variation exceeded the difference, so no demonstrated decode speedup. Comparison (../../tests/output/probes/hrx_performance/unreviewed/1792112820577230300/artifacts/report.json).
- Larger contexts/other models remain unverified. Merged prefill/router changes do not establish benefits for this dense IQ3_XXS decode workload.
- 2026-11-21: no retained patch applies to the current upstream heads (llama.cpp `76c3785b9`, HRX `b81ff778b`, rocm-systems `0ca1de96e9`). `tests/test-hrx-ops.cpp` no longer exists, and upstream has since landed IQ3_XXS skinny-matmul decoding (#200) and routed expert pairs (#175), the subject of two of them. The patch set and checkpoints describe the 2026-10-15 stack only; a fresh start would clone and fix forward.
- 2026-11-21 merge: the checkouts moved cleanly to llama.cpp `3e71ba3ff`, HRX `b6ad3f37e` and rocm-systems `6ac2f27c18`, after the build caches were repointed from the old `frameworks/llamacpp-additions` path. The rebuild then stopped at `hsa-runtime64.dll`, which could not link five `Wkmi::` symbols from `shared/amdgpu-windows-interop`; the installed runtime was unchanged.
- 2026-11-21 prerequisites. `wkmi.lib` is a DVC pointer, fetched anonymously from `s3://therock-dvc/rocm-systems` (`files/md5/4e/260c4aa37f97f3facf241f378e5b9e`) into `shared/amdgpu-windows-interop/wkmi/win/lib/`. ROCr configures with `Clang_DIR`/`LLVM_DIR` from `data/ROCm/therock-dist-windows-gfx110X-all-10.2.0a20260927/lib/llvm/lib/cmake`; HRX with `LOOM_TARGET_VM`, `LOOM_TARGET_ARCH_VM`, `AMDF_BUILD`, `IREE_ROCM_PATH` and `Python3_EXECUTABLE` (in `hrx/build.py`); llama.cpp with `hrx_DIR`, `loomc_DIR` and [packages.cmake](../../download/frameworks/llamacpp/hrx/packages.cmake), which imports the staged packages globally so the test targets see `hrx::hrx`. Every step needs the Visual Studio environment and CMake 4.2 or newer.
- 2026-11-21 result: ROCr and HRX build and stage. `llama-server` stops on two upstream MSVC defects in `ggml-hrx`: `M_PI` undeclared in `dispatch-rope-utils.h`, and a `graph-diagnostics.cpp` lambda with no return value (`C4716`). Our exported patch fixes the first with `target_compile_definitions(ggml-hrx PRIVATE _USE_MATH_DEFINES)`; `-DCMAKE_CXX_FLAGS=/D_USE_MATH_DEFINES` gets past it. The UI asset check also fails: the checkout's `dist` lacks `build.json`, `version.json` and the bundle files.

## Diagnosis retained

- Earlier codebook/fusion routing blockers were fixed. Initial incorrect fast routing broke chunked prefill and was rejected; corrected F32 output handling restored the intended path.
- Current-speed CPU attribution is about 15.42%, superseding the old 2.8% figure. Old 2.6 tok/s diagnostics are not current performance.
- Native Windows profiling has coverage/tooling limits; host scheduler timings are not GPU kernel attribution. Q2_K GPU matmul and further register/kernel analysis remain pending.

## Maintenance

- [Merge/build/validate/install/restore commands](../../download/frameworks/UPDATES.md#hrx).
- Saved local work: patches in [hrx-patches](hrx-patches/README.md), snapshots and the verified pointer in `state/llamacpp/hrx`, every local-only commit exported to `state/llamacpp/hrx/local-work` with a manifest, and the `codex/*` branches in the checkouts.
- Source/checkpoints: `frameworks/llamacpp/additions/hrx`; current state/pointers/patches: `state/llamacpp/hrx`.
- Modified checkouts/local commits require reviewed merges. New builds/native tests need explicit scope and long-run approval; preserve the working runtime on failure.
- Upstream/vendor availability differs from this custom Windows installation. Check actual support before treating a release as interchangeable.
- [Pending work](../../../notes/TODO.md), [historical outcomes](../../tests/notes/OUTCOMES.md).
