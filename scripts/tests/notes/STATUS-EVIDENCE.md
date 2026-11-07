# Verification evidence

Historical evidence and prior per-area scope; current status lives in [STATUS](STATUS.md).

| Prior scope | Evidence / limit |
| --- | --- |
| ASR | Whisper ABBA synthetic screen and Qwen API integration passed before later refactors; Gemma audio worked on both runtimes including 30 seconds. [Checkpoint](../../../notes/asr/ASR-IMPLEMENTATION.md) |
| Language-practice refactor | Whisper/Qwen API/chat, Gemma both runtimes, Parakeet CPU/Vulkan/VAD pass; browser/Handy pending. [Current evidence](../../../notes/NATIVE-VALIDATION.md) |
| Strata profile | Initial 36.3 tok/s median; final easy Pi task passed. [Profile](../../config/strata/REFERENCE.md) |
| Coding harnesses | Supplied easy tasks passed across compared clients; timings do not establish a universal ranking. [Guide](../../benchmarks/coding_agents/README.md) |
| llama.cpp tuning | Short MTP/ngram/context screens support scoped choices. [Rationale](../../config/llamacpp/SETTINGS.md) |
| Audio/sd.cpp | Native Kokoro/images pass; brief Breeze/Ming on v0.9.3 Vulkan/ROCm pass. Ming HTML cloning/streaming/browser smoke passes. [Current evidence](../../../notes/NATIVE-VALIDATION.md) |
| ComfyUI | Prior smoke/settings/tile screens have partial/scaling/quality limits. [Procedure](../../benchmarks/personal/comfyui/README.md) |
| HRX | Custom Windows runtime/operator/tensor/token checks passed at recorded versions; broader native coverage pending. [Evidence](../../config/llamacpp/HRX.md) |

- Selected historical evidence is retained; superseded probe/model/harness outputs were retired to trash (manifest included). Existing verified labels describe their recorded scope/version only.
