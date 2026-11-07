# Conversation workload scenarios

Scenario, matrix and measurement contract for the deployment layouts in [MULTIUSE.md](MULTIUSE.md).

## Three workload scenarios

1. Sequential resident turn: ASR -> Gemma -> TTS. Keep all models loaded.
2. Pipelined reply: start TTS on a stable text chunk while Gemma continues generating.
3. Interruption: feed ASR while TTS is generating/playing, optionally with Gemma
   still generating; detect the new turn and cancel queued/generated speech.

**10 layouts x 3 scenarios = 30 cells**, per fixed model/voice/language configuration.
The 21 tracked ASR options/16 configured resident profiles are a separate model/runtime inventory,
not another multiplier for this first deployment screen.

Start with the validated one-AudioCpp arrangement on both chat runtimes:
two layouts/six cells. Other layouts are conditional alternatives, not a mandatory grid.
Keep Kokoro fixed for ASR tests.

Record startup/loading separately, first partial, final-after-speech, first usable
LLM text, first audible TTS, cancellation delay, underruns and RAM/VRAM. Compare
idle residency with real overlapping work. Physical playback/microphone tests
also require echo handling; paced files cannot establish acoustic echo cancellation.

[Streaming/VAD groups](CAPABILITIES.md), [latency evidence](../../tests/notes/asr/ASR-LATENCY.md),
[shared GPU policy](../../config/notes/SHARED-GPU.md), [pending work](../../../notes/TODO.md).
