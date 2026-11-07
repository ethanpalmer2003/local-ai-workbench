# Additional ASR profiles

2026-10-28. Downloaded pinned Parakeet v3/Nemotron Q8 GGUFs; Ming reuses the
installed Audio Tiny Q4_K. File profiles and resident adapter catalog share model,
executable and mode definitions. The TTS configuration/defaults are unchanged.

## Brief validation

One warmup and one measured 5.3-second synthetic English clip. Loading/warmup
excluded; AppContainer false, administrator false. Task-owned servers cleaned up.

| Profile | Offline Vulkan request |
| --- | ---: |
| Parakeet TDT 0.6B v3 Q8 | 94 ms |
| Parakeet Nemotron 3.5 Q8 | 106 ms |
| AudioCpp Ming Audio Tiny Q4_K | 3.249 s |

[Resident evidence](../../output/asr/shared/resident_compare/unreviewed/1793233359234075000/artifacts/report.json).
All return the expected transcript on this clip; multilingual/noisy accuracy is
ungraded. Ming uses bounded expert offload and 96 generated tokens; no streaming.

Parakeet v3 offline Silero segmentation passes. Nemotron Vulkan streaming exits
with Windows access violation 0xC0000005; the same model/input passes on CPU.
The shared file profile explicitly selects CPU for streaming and Vulkan for offline.
The direct launcher requires `--build cpu --stream`; no silent fallback. Streaming
does not combine with offline VAD or `--json`. This is unpaced recorded audio,
not a microphone latency test.

[VAD check](../../output/asr/shared/resident_compare/unreviewed/1793233429648563300/artifacts/modes.json),
Vulkan failure (`scripts/state/logs/shared/parakeet-nemotron-stream-check.log`),
CPU streaming (`scripts/state/logs/shared/parakeet-nemotron-shared-stream-check.log`).
The VAD artifact retains the rejected JSON+stream attempt; the linked CPU log
records the corrected successful shared-profile run.

Usage: [Parakeet guide](../../../launchers/asr/PARAKEET.md),
[file-engine profiles](../../../launchers/asr/FILE-ENGINES.md).
Resident comparison selection: `--engines parakeetcpp-v3 parakeetcpp-nemotron-streaming audiocpp-ming-audio-tiny`.
These adapters do not establish shared gateway/browser integration.

34 focused model-free contracts pass. An initial normalization name collision was
fixed and regression-covered; failed run evidence is preserved.
