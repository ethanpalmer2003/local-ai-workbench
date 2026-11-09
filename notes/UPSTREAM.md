# Upstream issues and local patches

One index of known upstream defects and what this workspace does about them. Reports are local drafts;
nothing is posted to a third-party tracker. Patch owners keep the detail, this page keeps the map.

| Upstream | Symptom | Local response | Owner |
| --- | --- | --- | --- |
| KoboldCpp Lite | OpenAI speech arrives whole, so audio cannot play while the reply is generated | Proxy patches the Lite page at request time; a reviewable diff exists in two variants and no pull request was submitted | [patch guide](../scripts/launchers/koboldcpp/patches/README.md), [proxies](../scripts/launchers/PROXIES.md) |
| llama.cpp web UI | No workspace speech panel in the RDNA build | Two patches add the panel and its declarations, built into a local UI directory | [UI patches](../scripts/launchers/llamacpp/patches/README.md) |
| llama.cpp HRX build | Decode, bounds, MSVC and kernel issues on this custom Windows stack | Four patches with manifests; upstream availability differs from this build | [HRX patches](../scripts/config/llamacpp/hrx-patches/README.md) |
| Parakeet.cpp | Vulkan streaming crashes | Streaming disabled; the CPU C API adapter carries paced capture | [Parakeet guide](../scripts/launchers/asr/PARAKEET.md), [TODO](TODO.md) |
| AudioCpp Nemotron | Japanese streaming closes the stream or resets the connection although the model card lists `ja-JP` | Candidate engine only; the practice profile recognises through another backend | [TODO](TODO.md), [evaluation](asr/ASR-EVALUATION.md) |
| Lemonade Kokoro | French and Japanese come out wrong although the bundled espeak data has both | Unfiled draft with the evidence and the suspected language and style mapping | [draft](reviews/UPSTREAM-KOKORO-2026-11-08.md) |
| KoboldCpp Kokoro | Empty Japanese WAV, English fallback elsewhere | Unfiled draft: the build embeds an English phonemizer only | [draft](reviews/UPSTREAM-KOKORO-2026-11-08.md) |
| Strata | Not a defect: the comparison protocol comes from an upstream issue | The harness follows that protocol so its numbers stay comparable | [tuning](../scripts/config/strata/TUNING.md) |

Rules that keep this honest:

- A workaround that changes a vendor binary, page or build lives in its component folder with a patch, never as an edited vendor tree.
- A limitation without a workaround stays a TODO entry until the upstream fix is retested, and the entry names the trigger.
- A postable report is a draft in `notes/reviews/`; posting needs an explicit instruction, and the account token can only write content to this account's own repositories.
