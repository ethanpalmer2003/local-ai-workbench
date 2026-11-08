# Verification status

- [Practice alternatives](asr/ASR-PRACTICE-ALTERNATIVES.md): Qwen 0.6B, Whisper turbo and Parakeet v3 pass automatic Silero turns, Gemma replies and Vulkan Kokoro with both chat runtimes. English clip only; multilingual and microphone quality ungraded.

- [Nemotron runtimes](asr/NEMOTRON-STREAMING.md): AudioCpp/NeMo Vulkan and Parakeet CPU pass both practice gateways; matched latency and resource screen recorded. Microphone and multilingual quality ungraded.

- [Silero/Nemotron automatic turns](audiocpp/AUDIOCPP-VAD.md) pass silence, Kokoro coexistence and short-pause checks with 700 ms turn silence and 300 ms pre-roll. Both Gemma gateways pass saved-PCM integration; microphone and echo checks pending.

- [Paced ASR latency](asr/ASR-LATENCY.md): AudioCpp, NeMo and Qwen explicit-finalization screens pass, as do Qwen Silero-VAD and Parakeet v3 paced segments; Parakeet has no incremental adapter. Microphone and multilingual latency unranked.

- [Three additional ASRs](asr/ASR-EXTRA-PROFILES.md): Ming and Parakeet v3/Nemotron resident checks pass; v3 Silero VAD and CPU Nemotron streaming pass. Vulkan Nemotron streaming crashes, so the shared streaming profile uses CPU.

- [ASR evaluation](asr/ASR-SCREEN.md): 21 options tracked, all 16 configured resident profiles have brief checks; Cohere and Granite use synthetic English only. Microphone and multilingual accuracy unranked.

- TTS framework selection is AudioCpp, decided by the user; Piper, Sherpa and Kobold embedded TTS stay as alternatives and further TTS comparisons are closed. This is a workflow decision, not a cross-model quality ranking; Sherpa ASR stays in scope.

- [Kokoro/Piper follow-up](KOKORO-PIPER-SCREEN.md): a matched af_heart, five-thread CPU screen favors AudioCpp over Sherpa; Piper Lessac-high is faster than real time. Listening and multilingual quality ungraded.

- [Brief real-time screen](BRIEF-REALTIME-SCREEN.md): four TTS frameworks and both Gemma E4B runtimes with warmed timing; multilingual, playback and overlap unranked.

- Language recognition defaults to Qwen3-ASR 1.7B through llama.cpp: lowest pooled error on every language over 80 pinned clips (en 3.9%, es 2.3%, fr 4.6%, ja CER 5.5%) [report](output/shared/framework_compare/unreviewed/1794123067862277200/artifacts/report.json). Whisper Vulkan is the measured faster alternate (0.21 s vs 0.28 s p50) and replaces AudioCpp Nemotron, which failed Japanese.

- Four-arm comparison (practice, practice+Whisper, Lemonade, KoboldCpp) on the same Gemma weights, 80 clips: KoboldCpp starts fastest (12.0 s) but streams in coarser chunks, so 0.40 s TTFT is comparable and 15.2 chunks/s is not; Qwen3-ASR ranks first on all four languages [report](output/shared/framework_compare/unreviewed/1794123067862277200/artifacts/report.json).

- KoboldCpp internal speech is English-only despite accepting the same Kokoro voice ids: its `Kokoro_no_espeak_Q4` GGUF names 28 voices in `af`/`am`/`bf`/`bm` and none in `ef`/`ff`/`jf`/`zf`, so `jf_alpha` returned 0.00 s of audio and the Spanish and French rows used a fallback voice; none may be ranked.

- Pending work lives in [TODO](../../../notes/TODO.md). Path and type checks do not establish native runtime correctness.

- Freshness, last-run numbers and evidence: [capability matrix](CAPABILITY-MATRIX.md), regenerated with `python -m scripts.tools.capability_matrix`.

- Historical evidence and prior scope moved to [evidence](STATUS-EVIDENCE.md).

- Current validation: 615 non-live regressions pass (routing, cleanup, drift boundaries, Silero/duplex); types, structure, punctuation and size pass. [VAD evidence](audiocpp/AUDIOCPP-VAD.md) distinguishes native checks; [review index](../../../notes/reviews/README.md) owns review status.

- Report classification and execution-context rules: [test guide](../README.md).
