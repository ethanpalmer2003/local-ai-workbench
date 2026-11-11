# ASR evaluation

Reviewed 2026-10-28. [Capabilities](../../../launchers/asr/CAPABILITIES.md) group all
21 tracked options by streaming/VAD and installed-model scope. Sixteen have configured
resident profiles and all sixteen have saved brief checks. Cohere and Granite were checked
on two synthetic English clips with three repeats each; they are not in the timing table below.
[Additional profile setup/checks](ASR-EXTRA-PROFILES.md).

## Saved warmed screen

One identical 5.3-second synthetic English clip, one measured request after
warmup per profile. Startup/loading excluded. Approved execution recorded
AppContainer false, administrator false. HTTP parsing/transfer included;
Sherpa uses in-process C API. Runs were sequential subsets, not randomized pairs.

| Profile | Request ms |
| --- | ---: |
| Parakeet Vulkan, 110M English | 48 |
| AudioCpp Vulkan, Nemotron | 55 |
| speech.cpp, Qwen 0.6B | 63 |
| AudioCpp ROCm, Nemotron | 94 |
| llama.cpp, Qwen 1.7B | 116 |
| Parakeet CPU, 110M English | 129 |
| Sherpa CPU, English Zipformer | 229 |
| Whisper Vulkan/FA, turbo Q5 | 275 |
| Kobold Whisper, turbo Q5 | 459 |
| NeMo Vulkan, Nemotron | 506 |
| llama.cpp Gemma E4B audio | 2222 |

These are unpaced completed-file requests, not streaming first-partial or
end-of-speech latency. Different conversions/defaults prevent attributing every
gap to framework efficiency. Transcripts largely agree; practice/practice spelling
contributes to the uniform error score. This clip cannot rank recognition quality.

Evidence: NeMo/speech/Parakeet (../../output/asr/shared/resident_compare/unreviewed/1793214073218879900/artifacts/report.json),
AudioCpp (../../output/asr/shared/resident_compare/unreviewed/1793214404021681000/artifacts/report.json),
Whisper/Kobold (../../output/asr/shared/resident_compare/unreviewed/1793214561388104300/artifacts/report.json),
Qwen/Gemma (../../output/asr/shared/resident_compare/unreviewed/1793214646925748200/artifacts/report.json),
Sherpa (../../output/asr/shared/resident_compare/unreviewed/1793214776131600300/artifacts/report.json).

## Selection and next evidence

[Current picks, exclusions and reasons](../../../../notes/asr/ASR-EVALUATION.md) are owned
by the selection guide. [Matched Nemotron streaming](NEMOTRON-STREAMING.md) and
[automatic-turn alternatives](ASR-PRACTICE-ALTERNATIVES.md) supersede file timing
as the relevant latency evidence for practice. File numbers above remain evidence
for their original scope, not a universal framework ranking.

French/Spanish learner recordings, noise/silence and physical microphone checks
remain pending. [TODO](../../../../notes/TODO.md) owns follow-up work.
