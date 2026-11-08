# Verification status

- [Practice alternatives](asr/ASR-PRACTICE-ALTERNATIVES.md): Qwen 0.6B, Whisper turbo and Parakeet v3 pass automatic Silero turns, Gemma replies and Vulkan Kokoro with both chat runtimes. English clip only; multilingual/microphone quality ungraded.

- [Nemotron runtimes](asr/NEMOTRON-STREAMING.md): AudioCpp/NeMo Vulkan and Parakeet CPU pass both practice gateways; matched latency/resource screen recorded. Physical microphone/multilingual quality ungraded.

- [Silero/Nemotron automatic turns](audiocpp/AUDIOCPP-VAD.md) pass silence, Kokoro coexistence and short-pause checks with 700 ms turn silence/300 ms pre-roll; one AudioCpp server plus CPU VAD helper. Both Gemma practice gateways pass saved-PCM integration; physical microphone/echo checks pending.


- [Paced ASR latency](asr/ASR-LATENCY.md): AudioCpp/NeMo/Qwen explicit-finalization and Qwen Silero-VAD screens pass. Parakeet v3 now has paced VAD-segment practice checks; no incremental adapter. Microphone/multilingual latency remains unranked.

- [Three additional ASRs](asr/ASR-EXTRA-PROFILES.md): Ming and Parakeet v3/Nemotron resident checks pass; v3 Silero VAD and CPU Nemotron streaming pass. Vulkan Nemotron streaming crashes; shared streaming profile explicitly uses CPU.

- [ASR evaluation](asr/ASR-SCREEN.md): 21 options are tracked; all 16 configured resident profiles have saved brief checks. Cohere and Granite checks use synthetic English only. Real-time microphone and multilingual accuracy remain unranked.

- TTS framework selection resolved by user: AudioCpp. Piper/Sherpa and Kobold embedded TTS are retained alternatives; further TTS framework comparisons are closed. Prioritize natural multilingual voices in AudioCpp. This is a workflow decision, not a universal cross-model quality ranking; Sherpa ASR remains in scope.

- [Kokoro/Piper follow-up](KOKORO-PIPER-SCREEN.md): matched af_heart/five-thread CPU screen favors AudioCpp over Sherpa; heavier Piper Lessac-high remains faster than real time. Listening/multilingual quality ungraded.

- [Brief real-time screen](BRIEF-REALTIME-SCREEN.md): four TTS frameworks and both Gemma E4B runtimes checked with warmed timing; multilingual/playback/overlap remain unranked.

- Language recognition defaults to Whisper Vulkan: fastest of the measured recognisers and it reads all four practice languages. Qwen3-ASR 1.7B stays as a measured arm and scored lower pooled error on every language [over 80 pinned clips](output/shared/framework_compare/unreviewed/1794105071762308200/artifacts/report.json), so the faster default is a latency choice, not an accuracy one. Whisper replaces AudioCpp Nemotron, which misheard English and could not transcribe Japanese at all.

- Pending work lives in [TODO](../../../notes/TODO.md), not duplicated here. Static path/type checks do not establish native runtime correctness.

- Long-check freshness, last-run numbers and evidence links: [capability matrix](CAPABILITY-MATRIX.md), regenerated with `python -m scripts.tools.capability_matrix`.

- Historical evidence and prior per-area scope moved to [evidence](STATUS-EVIDENCE.md).
- Current validation: 363 non-live regressions pass, including practice/browser routing and cleanup, drift boundaries and Silero/duplex contracts; types, structure/docs and size checks pass. [VAD evidence](audiocpp/AUDIOCPP-VAD.md) distinguishes native checks; [review index](../../../notes/reviews/README.md) owns review status.
- Report classification and execution-context rules: [test guide](../README.md).
