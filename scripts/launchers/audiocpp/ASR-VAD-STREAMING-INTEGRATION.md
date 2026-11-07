# Streaming integration

Companion to [ASR-VAD.md](ASR-VAD.md), which owns the Silero model, settings and launcher command; this page covers the browser page loop, engine alternatives, gateway session and generated configs.

Both language-practice batches open `/practice` with this backend by default.
Press **Start listening** and grant microphone access. Continuous 16 kHz PCM feeds
Silero; a 700 ms pause submits the transcript to Gemma, then Kokoro speaks the
reply. Recognition receives silence during generation/playback to avoid tutor
self-transcription. This is sequential conversation, without voice interruption.
Choose English/Spanish/French for the corresponding Kokoro voice; auto detection
currently uses the English voice. Uploads and manual text remain available.

`ASR_SERVICE.engine` selects the llama.cpp default; the Kobold practice batch passes
`--transcription-engine audiocpp-nemotron`. Alternatives `speechcpp-qwen-0.6b`,
`whisper-vulkan` and `parakeetcpp-v3` use the same Silero settings and completed
turns, with separate resident ASR and Vulkan Kokoro servers. Parakeet v3 detects
language automatically. `qwen3-asr` and `gemma-audio` retain manual turns.
`nemo-nemotron` and `parakeetcpp-nemotron-cpu` retain incremental recognition
with shared Silero; see [streaming alternatives](../asr/NEMOTRON-STREAMING.md).
The shared controller is `asr/shared/turns.py`; reuse it for new adapters.

A shared bounded gateway session accepts complete 512-sample PCM16 frames, one
microphone session at a time. Stop cancels unfinished speech; page exit sends a
best-effort stop and 30 seconds without uploads expires the helper. Network lag
or turns above 30 seconds stop listening with an error. No silent truncation.
AudioWorklet capture requires localhost and a browser supporting 16 kHz capture.

Generated server configs are content-addressed under AudioCpp generated state;
the user's ordinary TTS config/defaults are unchanged. The shared config builder
also serves the coexistence test runner.
