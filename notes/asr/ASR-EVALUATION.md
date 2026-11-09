# ASR selection rationale

The configured engines and models are owned by `launcher_config`; this page records why each option exists.

Goal: English/French/Spanish conversation with Gemma E4B and Kokoro. Language
quality and runtime behavior are separate; synthetic English checks do not rank
learner accents or multilingual accuracy.

## Runtime choices

| Runtime/profile | Decision | Reason and limit |
| --- | --- | --- |
| AudioCpp Vulkan + Nemotron 3.5 | Keep | True streaming with the shared ASR/Kokoro server and the best final latency; NeMo still produced earlier partials. |
| NeMo-Speech.cpp Vulkan + Nemotron | Keep alternative | Fastest first partial and lowest VRAM in the streaming screen, at the cost of the slowest final; separate Kokoro server. |
| Parakeet.cpp CPU + Nemotron | Keep for GPU pressure | Paced streaming works off-GPU; about 1.1 GiB sampled RAM and optional pinned C API build. |
| Parakeet.cpp Vulkan + Nemotron | Disabled pending fix | Streaming crashes; offline decoding still works. |
| whisper.cpp Vulkan/FA + turbo Q5 | Keep accuracy baseline | Multilingual automatic turns; slower completed-turn decode. Learner/noisy quality may justify it. |
| Kobold embedded Whisper | Deprioritize | Same model as whisper.cpp, slower file screen, no demonstrated advantage. |

## Other model choices

| Model/setup | Decision and reason |
| --- | --- |
| AudioCpp Cohere Transcribe 2B | Unranked: brief English resident check passes; multilingual/noisy quality and resources unmeasured. |
| Granite Speech 2B | Unranked: brief English resident check passes; multilingual/noisy quality and resources unmeasured. |
| Qwen3-ASR 0.6B / speech.cpp | Keep: fast multilingual completed-turn option; quality versus Nemotron ungraded. |
| Parakeet v3 0.6B | Keep: fast multilingual European-language comparator. Current practice path decodes completed VAD segments. |
| Gemma E4B audio | Lower priority: shares chat weights but is slow on the short screen; no incremental adapter. |
| Ming Audio Tiny | Lower priority: slow with expert offload; no incremental adapter or quality benefit shown. |
| Qwen3-ASR 1.7B | Conversation practice and TTS reference transcription: best multilingual accuracy on the pinned corpus. |
| Parakeet 110M | English-only reference; the Sherpa ASR weights were retired on 2026-11-08. |
| Handy | Dictation frontend, not a competing recognition model; manual workflow checks remain. |

Promote alternatives only after matched learner recordings compare accuracy,
latency and resources. Separate CPU/GPU, loading, first partial and final text;
label failures, unsupported languages and untested quality distinctly.

Evidence: [streaming runtimes](../../scripts/tests/notes/asr/NEMOTRON-STREAMING.md),
[automatic alternatives](../../scripts/tests/notes/asr/ASR-PRACTICE-ALTERNATIVES.md),
[file screen](../../scripts/tests/notes/asr/ASR-SCREEN.md),
Cohere/Granite brief checks (../../scripts/tests/output/asr/shared/resident_compare/unreviewed/1793254500105109300/artifacts/report.json),
[capabilities](../../scripts/launchers/asr/CAPABILITIES.md),
[language coverage](../../scripts/config/notes/MODEL-LANGUAGES.md).
TTS framework selection is separate: [AudioCpp choice](../../scripts/launchers/audiocpp/RETAINED-TTS.md).
