# Upstream issues and local patches

Every upstream defect with a recorded local response, split by whether a local build is involved; reports stay local.

## No rebuild

| Upstream | Symptom | Local response | Owner |
| --- | --- | --- | --- |
| KoboldCpp Lite | OpenAI speech arrives whole, so audio cannot play while the reply generates | Proxy patches the Lite page at request time; two reviewable variants, no pull request | [patch guide](../scripts/launchers/koboldcpp/patches/README.md), [proxies](../scripts/launchers/PROXIES.md) |
| llama.cpp web UI | No workspace speech panel in the RDNA build | Two patches add the panel, built into a local UI directory | [UI patches](../scripts/launchers/llamacpp/patches/README.md) |
| llama.cpp Vulkan | Freezes on the fourth 256-token generation | Long runs use the Lemonade build; [draft](reviews/LLAMACPP-VULKAN-2026-11-09.md) | [benchmarks](../scripts/benchmarks/llamacpp/README.md) |
| llama.cpp ROCm (Lemonade release) | b1373 (2026-11-11) aborts at startup: `ggml_backend_cuda_init` reports device -1 and the process stops with 0x80000003. b1372 loads and runs the profile screen | Reinstalled b1372; retest the next release | [tuning](../scripts/config/llamacpp/TUNING.md) |
| Parakeet.cpp | Vulkan streaming crashes | Streaming disabled; the CPU adapter carries paced capture; retest after an upstream fix | [guide](../scripts/launchers/asr/PARAKEET.md) |
| NeMo-Speech.cpp | Server exits during startup with `GGML_ASSERT(ne1 == ne11) failed` in the CPU graph while the Vulkan session reports a rnnt head | Candidate engine only; the practice profile uses Qwen3-ASR; retest after a build change | [evaluation](asr/ASR-EVALUATION.md) |
| AudioCpp Nemotron | Japanese streaming closes or resets despite `ja-JP` | Candidate engine only; the practice profile uses another backend; retest after a build change | [evaluation](asr/ASR-EVALUATION.md) |
| ComfyUI requirements | Plain `torch` would replace the ROCm build on update | Updater filters torch before installing | vendor updater |
| rocm-sdk wheels | A DLL moves between core and devel packages; some targets lack MIOpen/rocBLAS | Installer copies the DLL; launch skips absent paths | vendor installer, [bootstrap](../bat/browser/comfyui/comfyui_bootstrap.bat) |
| Triton with INT8-Fast-ROCM | The backend crashes the server with that node loaded | Backend stays off | [bootstrap](../bat/browser/comfyui/comfyui_bootstrap.bat) |
| ROCm torch | Invalid kernel file error on one device | `HIP_VISIBLE_DEVICES` escape hatch stays commented | [bootstrap](../bat/browser/comfyui/comfyui_bootstrap.bat) |
| sageattention wheel | Rebuilt wheels keep one version, so pip skips them | Updater force-reinstalls it | vendor updater |

The ComfyUI install is a self-updating clone that is not edited locally; owned files and the node check are in its
[configuration](../scripts/config/comfyui/README.md). Partner and API nodes stay off as policy.

## Rebuild, implemented

| Upstream | Symptom | Local response | Owner |
| --- | --- | --- | --- |
| Avalon | `close()` in `ggml/src/ggml-cuda/moe-cache.cu` does not compile with MSVC | One local commit, replayed with `pull --rebase --autostash`; a pulled commit still needs a build | [maintenance](../scripts/download/frameworks/UPDATES-COMPONENTS.md) |

## Rebuild, deferred

| Upstream | Symptom | Why deferred |
| --- | --- | --- |
| HRX llama.cpp | Decode, bounds, MSVC and kernel issues on this Windows stack | Patches exist, but upstream changes too fast to keep re-merging; the IQ3_XXS analysis and latest-source build wait with it ([patches](../scripts/config/llamacpp/hrx-patches/README.md)) |
| Lemonade Kokoro | Recipe maps French and Japanese wrongly although its espeak data ships both | Needs a corrected recipe in its own config; no rebuild planned, revisit with one ([draft](reviews/UPSTREAM-KOKORO-2026-11-08.md)) |
| KoboldCpp Kokoro | Empty Japanese WAV, English fallback elsewhere: the build embeds one phonemizer | Needs a build embedding another phonemizer; revisit with one ([draft](reviews/UPSTREAM-KOKORO-2026-11-08.md)) |

Rules that keep this honest:

- A fix that needs no rebuild lives beside its component as a patch, proxy or config, never as an edited vendor tree.
- A rebuild fix is either an implemented local commit or a deferred entry above, which names the reason and what would revisit it.
- A postable report is a draft in `notes/reviews/`; posting needs an explicit instruction, and the account token can only write content to this account's own repositories.
