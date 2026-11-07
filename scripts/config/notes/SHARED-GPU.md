# Shared GPU policy

- Conversation ASR/chat/TTS layouts and concurrency checks: [multi-use guide](../../launchers/asr/MULTIUSE.md).

- Owner: [shared_gpu.py](../../launchers/runtime/shared_gpu.py); combined launcher: `bat/browser/launch_kobold.bat --with-image`.
- `--usage-profile shared` applies explicit co-resident settings; standalone keeps native defaults. No automatic VRAM reservation/model unloading.

| Component | Shared profile |
| --- | --- |
| sd.cpp | Selected Q4 model, CPU text encoder, 512 VAE tiles |
| AudioCpp Breeze | Selected quantized GPU model; no supported partial CPU offload |
| AudioCpp Drama | 40 CPU expert layers; other native session settings preserved |
| Ming Tiny | Only with compatible loaders/config; not enabled/tested |
| Rocinante Kobold | Vulkan, 16 GPU layers, original 16K context/Q8 KV |

- Layer policy is model-specific; other Kobold models retain their configured overrides.
- Native AudioCpp lacks CLI session-option overrides; shared startup derives `state/generated/audiocpp/shared-<port>.json` from the base JSON. Edit the source/policy, not generated files.
- Service enabled settings still apply; `--with-image` enables images for that launch.
- Live benchmark module: `scripts.benchmarks.koboldcpp.kobold_stack_vram`; opt-in, preserves conflicting sessions and records loading/generation/cleanup context.
- Prefer [images on demand](IMAGE-ON-DEMAND.md) for model swapping rather than simultaneous residency.
- [Measured outcomes](../../tests/notes/OUTCOMES.md); current settings are scoped to tested workloads, not universal limits.
