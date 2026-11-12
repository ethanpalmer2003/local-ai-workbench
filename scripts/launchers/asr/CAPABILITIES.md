# ASR capabilities

[Multi-use arrangements and test counts](MULTIUSE.md) cover shared models,
multiple servers, concurrent ASR/chat/TTS and interruption handling.

Profile counts, streaming/VAD terminology and pacing status: see
[CAPABILITIES-NOTES.md](CAPABILITIES-NOTES.md).

| Selected profile(s) | Recognition group | VAD support / local state |
| --- | --- | --- |
| AudioCpp Vulkan/ROCm | Stateful streaming; multilingual | [Silero turn controller](../audiocpp/ASR-VAD.md) connected/tested with Vulkan; ROCm VAD path untested |
| AudioCpp Qwen3-ASR | Fixed-window streaming with partial results; 31 languages | Silero practice turns plus 3 s decode windows; first caption 3.2 s into speech, final 0.10 s after it |
| NeMo-Speech.cpp | Stateful streaming; multilingual | Shared Silero practice controller connected; runtime endpointing set to 10 s so Silero owns the 700 ms turn end |
| speech.cpp | VAD-delimited live utterances; multilingual | Silero in native live mode; shared automatic practice turns use completed-segment decoding |
| Whisper Vulkan/FA | Offline; upstream windowed live example | Shared Silero automatic practice turns; native server VAD remains off |
| Kobold Whisper | Completed audio requests | No dedicated VAD exposed by this adapter; external gating needed |
| llama.cpp audio adapter | Completed audio requests in this adapter | External gating needed; toolkit streaming does not establish this port's support |
| Gemma audio, llama.cpp/Kobold | Prompted completed clips, maximum 30 seconds | External gating needed; no incremental adapter |
| Parakeet CPU/Vulkan | Offline; English only | Optional Silero downloaded and enabled in file launcher; benchmark server differs |
| AudioCpp audio model | Offline ASR adapter validated; expert offload | VAD chain unconfigured |
| Handy | GUI dictation; not a backend comparator | Upstream integrated Silero; manual local validation pending |
| Parakeet alternatives | Downloaded: Vulkan offline; CPU streaming passes, Vulkan streaming crashes | Segmented practice; CPU streaming uses paced C API/shared Silero; file VAD off for streaming |
| Legacy Whisper Vulkan | Disabled | Excluded from active testing |

References: [AudioCpp ASR](https://github.com/0xShug0/audio.cpp/blob/main/docs/asr.md),
[VAD models](https://github.com/0xShug0/audio.cpp/blob/main/docs/speech_analysis.md),
[NeMo](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/cli.md),
[speech.cpp](https://github.com/nyosegawa/speech.cpp/blob/main/docs/models/qwen3-asr.md),
[Whisper](https://github.com/ggml-org/whisper.cpp#voice-activity-detection-vad),
[Parakeet](https://github.com/mudler/parakeet.cpp),
[Handy](https://github.com/cjpais/Handy).
