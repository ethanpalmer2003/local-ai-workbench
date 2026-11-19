# Upstream issues and local patches

Index only: one symptom and the local response per entry, with the component guide owning the fix.

Symptom entries record what this machine saw, not confirmed upstream defects; each names the local
response that followed. Split by whether a local build is involved.

## No rebuild

| Upstream | Symptom on this machine | Local response | Owner |
| --- | --- | --- | --- |
| KoboldCpp Lite | Speech arrives whole, so audio cannot play while the reply generates | Proxy patches the Lite page at request time; two reviewable variants, no pull request | [patch guide](../scripts/launchers/koboldcpp/patches/README.md), [proxies](../scripts/launchers/PROXIES.md) |
| llama.cpp web UI | No workspace speech panel in the RDNA build | Two patches add the panel in a local UI directory | [UI patches](../scripts/launchers/llamacpp/patches/README.md) |
| llama.cpp Vulkan | Froze on the fourth 256-token generation on the build before b12363 | No recurrence in six 512-token generations at 16k and 32k on b12363; the request budget stays as the guard | [draft](reviews/LLAMACPP-VULKAN-2026-11-09.md) |
| llama.cpp Vulkan b12421 | The embedding server exits with `0xC0000005` (access violation) four inputs into the first multi-text `/v1/embeddings` request; single-text requests of the same strings run 400 times without a fault, and ROCm b1377 serves the same batches | Embedding checks run against the ROCm build with `HIP_VISIBLE_DEVICES=0` and `--no-server`; matches the open [PR #32044](https://github.com/ggml-org/llama.cpp/pull/32044) fixing an out-of-bounds read from an MTP hidden-state width ([#32036](https://github.com/ggml-org/llama.cpp/issues/32036)); v1.0.0 (b12359) serves the batch normally, so the regression is later than 1.0.0 | [similarity](../scripts/review/SIMILARITY.md) |
| llama.cpp Vulkan b12422, prefill | The 27B server exits with `0xC0000005` during a 3.7K-token re-prefill after shorter requests succeeded, and it does so with speculation off as well: `swift15-nospec` really sends `--spec-type none` and still exits at the same point. Reported upstream as Vulkan MTP instability where the server "survives one or two shorter prompts, then crashes on a longer" ([#23769](https://github.com/ggml-org/llama.cpp/issues/23769)) and as a `draft-mtp` prefill device-lost ([turboquant #185](https://github.com/TheTom/llama-cpp-turboquant/issues/185)), neither of which explains a run without the drafter | The same 27B runs both tasks on ROCm, so the pair is measured there; the Vulkan arm runs the `vulkan-1.0.0` pin, which is clean on both failures, and the rolling install was archived so there is nothing newer to retest until its catalog entry is applied again | [builds](../scripts/config/llamacpp/BUILDS.md) |
| Strata 0.1.60 | The engine's test start failed so the updater kept 0.1.59, while control reached 0.1.60, which then exits before serving: its image encoder child cannot start (`WinError 5`, `vision.exe` is empty in the native config) | The framework updater checks Strata and never installs it; benchmarks pass a vision-free config until the app realigns the parts | [configuration](../scripts/config/strata/README.md) |
| llama.cpp ROCm (Lemonade release) | b1373 and b1375 die while building the context with `ROCm error: unspecified launch failure`, `current device: -1`, when the Ryzen iGPU is visible as a second ROCm device; b1372 tolerated it | The build entry hides the iGPU (`HIP_VISIBLE_DEVICES=0`), which loads and decodes at 51-56 tok/s; `--device ROCm0` alone does not help | [tuning](../scripts/config/llamacpp/TUNING.md), [note](reviews/ROCM-DRIVER-TIMEOUT-2026-11-13.md) |
| Parakeet.cpp | Vulkan streaming crashes here | Streaming disabled; the CPU adapter carries paced capture; retest after a build change | [guide](../scripts/launchers/asr/PARAKEET.md) |
| NeMo-Speech.cpp | Startup exits here with `GGML_ASSERT(ne1 == ne11) failed` in the CPU graph while Vulkan reports a rnnt head | Candidate engine only; practice uses Qwen3-ASR | [evaluation](asr/ASR-EVALUATION.md) |
| Loom 0.2.0 (`ROCm/hrx-system`) | `loom-serve` cannot open the AMD GPU: `--device=amdgpu`, `rdna`, `rdna://1` and `amdgpu://1` each answer `NOT_FOUND; no AMD endpoint matches the selected family and path` (`runtime/src/iree/hal/driver/amd/driver.c:843`) and exit 1, with `HIP_VISIBLE_DEVICES` and `ROCR_VISIBLE_DEVICES` set to 0 or 1. The same release's `amdf-info` does create a device: `--format=json` lists `AMD Radeon RX 7800 XT` (`gfx1102`, ordinal 1) and `AMD Radeon(TM) Graphics` (`gfx1031`, 2 CU, ordinal 0), and `--device=rdna --activate` reports `Activation: OK` on `rdna://0`, the integrated one. `--device=task` starts the server and registers `Qwen/Qwen2.5-0.5B-Instruct`, but a chat request still answered 503 after four minutes, so the CPU preparation was unfinished | Candidate engine only, tracked as `loom/sdk`, `loom/serve` and `loom/tools`; the model package fetches and loads, so the fault is device acquisition rather than the package. llama.cpp Vulkan is the baseline (472 tok/s median, five 128-token runs). Nothing is filed: the next step is a device document or an upstream question once the CPU path is known to finish | [catalog](../scripts/download/frameworks/PLATFORMS.md) |
| AudioCpp Nemotron | Japanese streaming closes or resets despite `ja-JP` | Candidate engine only; practice uses another backend; retest after a build change | [evaluation](asr/ASR-EVALUATION.md) |
| ComfyUI requirements | Plain `torch` would replace the ROCm build | Updater filters torch before installing | vendor updater |
| ComfyUI custom node fetch | A large node repository stops mid-transfer: `RPC failed; curl 18`, `early EOF`, `fetch-pack: invalid index-pack output`, so the update does not land | Rerun the updater: the retry on 2026-11-15 landed commit `14281222` and all three tracked nodes. It runs attached now and reports a failure as `CHECK FAILED`; a shallow clone or a larger `http.postBuffer` is the fallback | [bootstrap](../bat/browser/comfyui/comfyui_bootstrap.bat) |
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
