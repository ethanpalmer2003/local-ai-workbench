# Verification status

- [Practice alternatives](asr/ASR-PRACTICE-ALTERNATIVES.md): Qwen 0.6B, Whisper turbo and Parakeet v3 pass automatic Silero turns, Gemma replies and Vulkan Kokoro with both chat runtimes. English clip only; multilingual and microphone quality ungraded.

- [Nemotron runtimes](asr/NEMOTRON-STREAMING.md): AudioCpp/NeMo Vulkan and Parakeet CPU pass both practice gateways; matched latency and resource screen recorded. Microphone and multilingual quality ungraded.

- [Silero/Nemotron automatic turns](audiocpp/AUDIOCPP-VAD.md) pass silence, Kokoro coexistence and short-pause checks at the configured turn timing. Both Gemma gateways pass saved-PCM integration; microphone and echo checks pending.

- [Paced ASR latency](asr/ASR-LATENCY.md): AudioCpp, NeMo and Qwen explicit-finalization screens pass, as do Qwen Silero-VAD and Parakeet v3 paced segments; Parakeet has no incremental adapter. Microphone and multilingual latency unranked.

- [Three additional ASRs](asr/ASR-EXTRA-PROFILES.md): Ming and Parakeet v3/Nemotron resident checks pass; v3 Silero VAD and CPU Nemotron streaming pass. Vulkan Nemotron streaming crashes, so the shared streaming profile uses CPU.

- [ASR evaluation](asr/ASR-SCREEN.md): every configured resident profile has a brief check; Cohere and Granite use synthetic English only. Microphone and multilingual accuracy unranked.

- TTS framework selection is AudioCpp, decided by the user; Piper, Sherpa and Kobold embedded TTS stay as alternatives and further TTS comparisons are closed. This is a workflow decision, not a cross-model quality ranking; Sherpa ASR stays in scope.

- [Kokoro/Piper follow-up](KOKORO-PIPER-SCREEN.md): a matched af_heart, five-thread CPU screen favors AudioCpp over Sherpa; Piper Lessac-high is faster than real time. Listening and multilingual quality ungraded.

- [Brief real-time screen](BRIEF-REALTIME-SCREEN.md): four TTS frameworks and both Gemma E4B runtimes with warmed timing; multilingual, playback and overlap unranked.

- Language recognition defaults to Qwen3-ASR 1.7B through llama.cpp: lowest pooled error on every language over 80 pinned clips. Whisper Vulkan is the measured faster alternate and replaces AudioCpp Nemotron, which failed Japanese. [Report](output/shared/framework_compare/unreviewed/1794123067862277200/artifacts/report.json).

- Four-arm comparison (practice, practice+Whisper, Lemonade, KoboldCpp) on the same Gemma weights and 80 clips: KoboldCpp starts fastest but streams in coarser chunks, so its time to first token is comparable and its chunk rate is not; Qwen3-ASR ranks first on all four languages. [Report](output/shared/framework_compare/unreviewed/1794123067862277200/artifacts/report.json).

- KoboldCpp internal speech is English-only despite accepting the same Kokoro voice ids: its Kokoro GGUF carries English voice families only, so the Japanese sentence returned an empty WAV and the Spanish and French rows used a fallback voice. None of those rows may be ranked. [Report](output/shared/framework_compare/unreviewed/1794123067862277200/artifacts/report.json).

- Pending work lives in [TODO](../../../notes/TODO.md). Path and type checks do not establish native runtime correctness.

- Freshness, last-run numbers and evidence: [capability matrix](CAPABILITY-MATRIX.md), regenerated with `python -m scripts.tools.capability_matrix`.

- Historical evidence and prior scope moved to [evidence](STATUS-EVIDENCE.md).

- Current validation: 615 non-live regressions pass (routing, cleanup, drift boundaries, Silero/duplex); types, structure, punctuation and size pass. [VAD evidence](audiocpp/AUDIOCPP-VAD.md) distinguishes native checks; [review index](../../../notes/reviews/README.md) owns review status.

- Report classification and execution-context rules: [test guide](../README.md).
