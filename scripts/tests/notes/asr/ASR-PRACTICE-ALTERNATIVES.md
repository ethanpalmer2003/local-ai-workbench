# Automatic practice alternatives

2026-10-28: Qwen 0.6B, Whisper turbo and Parakeet v3 pass brief saved-audio
practice checks, each with both llama.cpp and Kobold Gemma E4B plus Vulkan Kokoro.
The practice default is `audiocpp-qwen3` ([launcher guide](../../../launchers/asr/README.md)).

Each alternative keeps its decoder resident and recognizes a complete Silero
segment. These adapters do not emit incremental transcript updates. All share
the controller, threshold 0.5, 700 ms silence, 300 ms pre-roll and 16 kHz input.
They use separate ASR/Kokoro servers plus the small CPU Silero helper.

| Alternative | Decode request | Final after Silero-estimated speech end |
| --- | ---: | ---: |
| AudioCpp Nemotron Vulkan | Incremental during speech | 0.96-1.09 s |
| speech.cpp Qwen 0.6B Q8 | 125-157 ms | 1.09-1.22 s |
| Whisper Vulkan/FA turbo Q5 | 221-258 ms | 1.22-1.24 s |
| Parakeet v3 Vulkan Q8 | 140-160 ms | 1.22-1.23 s |

Ranges are two samples, one per chat runtime, on the same synthetic English clip.
Final timing includes silence detection and 128 ms upload/poll scheduling; the
marker is Silero's estimate, not labeled speech end. Transcripts differ only in
punctuation, so this cannot rank multilingual accuracy. The matched Nemotron
rerun uses the same clip, VAD settings and polling; its 0.1-0.3 s advantage is a
brief screen, not percentile evidence.

## Embedded Whisper against the two AudioCpp recognizers

2026-11-24: same clip, gateway and KoboldCpp runtime, two passes each, AppContainer
false. AudioCpp has no Whisper model of its own.

| Recognizer | Delivery | First partial | Final after speech end |
| --- | --- | ---: | ---: |
| AudioCpp Qwen3-ASR 1.7B (practice default) | Streaming, automatic turns | 3.33 s | 1.09-1.12 s |
| AudioCpp Nemotron 3.5 | Streaming, automatic turns | 1.15 s | 1.09-1.12 s |
| Kobold embedded Whisper Q5 | Whole uploaded turn, 286-312 ms decode | none | 0.99-1.01 s |

Both AudioCpp engines reach the same final and differ only in when captions
appear; the default trades about two seconds of waiting for the best multilingual
accuracy on the pinned corpus, and `--practice-ui` starts it on both pages.
Embedded Whisper finishes about 0.1 s sooner, but the gateway refuses a whole-file
recognizer on `/asr/live`: the page would upload a finished turn and show nothing
while the speaker talks, so `--transcription-engine embedded` stays an option.
Evidence: practice_smoke runs `1795577036774874600`, `1795576425940897300` and
`1795576405044802300` under `scripts/tests/output/asr/shared/practice_smoke/unreviewed/2026-11-24/`.

Startup/model loading, warmup and cleanup are separate shared-lifecycle phases.
Kokoro and ASR receive warmup inference before the measured flow. Approved native
execution recorded AppContainer false, administrator false. Isolated ports
19193-19196 were used; only owned services were stopped. No packages/downloads.

- Matched warmed Nemotron report (../../output/asr/shared/practice_smoke/unreviewed/1793243169742135300/artifacts/report.json)
- Qwen report (../../output/asr/shared/practice_smoke/unreviewed/1793240745550505200/artifacts/report.json)
- Whisper report (../../output/asr/shared/practice_smoke/unreviewed/1793240821767065100/artifacts/report.json)
- Parakeet report (../../output/asr/shared/practice_smoke/unreviewed/1793240912527630200/artifacts/report.json)

Select them with `--transcription-engine` on either language-practice launcher.
[Launch/settings guide](../../../launchers/asr/README.md).
Reproduce with `python -m scripts.tests.cases.asr.shared.practice_smoke --engine`
and `speechcpp-qwen-0.6b`, `whisper-vulkan` or `parakeetcpp-v3`; add `--runtimes
koboldcpp` for `embedded`.

Physical microphone, acoustic echo, learner accents, French/Spanish and resource
ranking remain pending. Parakeet v3 automatically detects language; the UI's
language choice still controls the tutor and Kokoro voice.

Nemotron uploads/warmup use its streaming transport, matching the configured
model mode. The rejected completed-file warmup artifact remains preserved.
