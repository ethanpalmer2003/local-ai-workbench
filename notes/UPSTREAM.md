# Upstream issues and local patches

Symptom entries record what this machine saw, not confirmed upstream defects; each names the local
response that followed. Split by whether a local build is involved.

## No rebuild

| Upstream | Symptom on this machine | Local response | Owner |
| --- | --- | --- | --- |
| KoboldCpp Lite | Speech arrives whole, so audio cannot play while the reply generates | Proxy patches the Lite page at request time; two reviewable variants, no pull request | [patch guide](../scripts/launchers/koboldcpp/patches/README.md), [proxies](../scripts/launchers/PROXIES.md) |
| llama.cpp web UI | No workspace speech panel in the RDNA build | Two patches add the panel in a local UI directory | [UI patches](../scripts/launchers/llamacpp/patches/README.md) |
| llama.cpp Vulkan | Froze on the fourth 256-token generation on the build before b12363 | No recurrence in six 512-token generations at 16k and 32k on b12363; the request budget stays as the guard | [draft](reviews/LLAMACPP-VULKAN-2026-11-09.md) |
| llama.cpp ROCm (Lemonade release) | b1373 and b1375 die while building the context with `ROCm error: unspecified launch failure`, `current device: -1`, when the Ryzen iGPU is visible as a second ROCm device; b1372 tolerated it | The build entry hides the iGPU (`HIP_VISIBLE_DEVICES=0`), which loads and decodes at 51-56 tok/s; `--device ROCm0` alone does not help | [tuning](../scripts/config/llamacpp/TUNING.md), [note](reviews/ROCM-DRIVER-TIMEOUT-2026-11-13.md) |
| Parakeet.cpp | Vulkan streaming crashes here | Streaming disabled; the CPU adapter carries paced capture; retest after a build change | [guide](../scripts/launchers/asr/PARAKEET.md) |
| NeMo-Speech.cpp | Startup exits here with `GGML_ASSERT(ne1 == ne11) failed` in the CPU graph while Vulkan reports a rnnt head | Candidate engine only; practice uses Qwen3-ASR | [evaluation](asr/ASR-EVALUATION.md) |
| AudioCpp Nemotron | Japanese streaming closes or resets despite `ja-JP` | Candidate engine only; practice uses another backend; retest after a build change | [evaluation](asr/ASR-EVALUATION.md) |
| ComfyUI requirements | Plain `torch` would replace the ROCm build | Updater filters torch before installing | vendor updater |
| rocm-sdk wheels | A DLL moves between packages; some targets lack MIOpen/rocBLAS | Installer copies the DLL; launch skips absent paths | vendor installer, [bootstrap](../bat/browser/comfyui/comfyui_bootstrap.bat) |
| Triton with INT8-Fast-ROCM | The backend crashes the server with that node | Backend stays off | [bootstrap](../bat/browser/comfyui/comfyui_bootstrap.bat) |
| ROCm torch | Invalid kernel file error on one device | `HIP_VISIBLE_DEVICES` escape hatch stays commented | [bootstrap](../bat/browser/comfyui/comfyui_bootstrap.bat) |
| sageattention wheel | Rebuilt wheels keep one version, so pip skips them | Updater force-reinstalls | vendor updater |

The ComfyUI install self-updates and is never edited locally; see its
[configuration](../scripts/config/comfyui/README.md). Partner and API nodes stay off as policy.

## Rebuild, implemented

| Upstream | Symptom on this machine | Local response | Owner |
| --- | --- | --- | --- |
| Avalon | `close()` in `ggml/src/ggml-cuda/moe-cache.cu` does not compile with MSVC | One local commit, replayed with `pull --rebase --autostash`; a pulled commit still needs a build | [maintenance](../scripts/download/frameworks/UPDATES-COMPONENTS.md) |

## Rebuild, deferred

| Upstream | Symptom on this machine | Why deferred |
| --- | --- | --- |
| HRX llama.cpp | Decode, bounds, MSVC and kernel issues on this Windows stack | Patches exist, but upstream changes too fast to keep re-merging; the IQ3_XXS analysis and latest-source build wait with it ([patches](../scripts/config/llamacpp/hrx-patches/README.md)) |
| Lemonade Kokoro | Recipe maps French and Japanese wrongly although its espeak data ships both | Needs a corrected recipe in its own config; no rebuild planned, revisit with one ([draft](reviews/UPSTREAM-KOKORO-2026-11-08.md)) |
| KoboldCpp Kokoro | Empty Japanese WAV, English fallback elsewhere: the build embeds one phonemizer | Needs a build embedding another phonemizer; revisit with one ([draft](reviews/UPSTREAM-KOKORO-2026-11-08.md)) |

Rules that keep this honest:

- A fix that needs no rebuild lives beside its component as a patch, proxy or config, never as an edited vendor tree.
- A rebuild fix is either an implemented local commit or a deferred entry above, which names the reason and what would revisit it.
- A postable report is a draft in `notes/reviews/`; posting needs an explicit instruction.
