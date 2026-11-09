# Automatic practice alternatives



2026-10-28: Qwen 0.6B, Whisper turbo and Parakeet v3 pass brief saved-audio

practice checks, each with both llama.cpp and Kobold Gemma E4B plus Vulkan Kokoro.

Qwen 1.7B was excluded as requested. Nemotron remains the default.



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



Ranges are two samples, one per chat runtime, using the same synthetic English

clip. Final timing includes silence detection and 128 ms upload/poll scheduling;

the marker is Silero's estimate, not human-labelled speech end. All transcripts

agree in wording apart from punctuation. This cannot rank multilingual accuracy.

The matched Nemotron rerun uses the same clip, VAD settings and gateway polling.

Its advantage is about 0.1-0.3 seconds here; 128 ms scheduling and two samples

limit confidence. This is a brief screen, not stable percentile evidence.



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

and `speechcpp-qwen-0.6b`, `whisper-vulkan` or `parakeetcpp-v3`.



Physical microphone, acoustic echo, learner accents, French/Spanish and resource

ranking remain pending. Parakeet v3 automatically detects language; the UI's

language choice still controls the tutor and Kokoro voice.



356 model-free regressions pass; types, structure/docs and code-size checks pass.

An earlier concurrent run timed out in an unrelated proxy-config fixture; its

log is preserved. The final suite ran after native cleanup.



Nemotron uploads/warmup now use its streaming transport, matching the configured

model mode. The rejected completed-file warmup artifact remains preserved.

Ten focused practice contracts and type checks pass after this correction.

