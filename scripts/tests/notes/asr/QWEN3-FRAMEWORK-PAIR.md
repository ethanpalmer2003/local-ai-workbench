# Qwen3-ASR 1.7B: AudioCpp against llama.cpp

Does the framework that serves Qwen3-ASR fastest change the default recogniser? Same model, two
conversions, one resident comparison.

Run: `python -m scripts.benchmarks.asr.asr_resident_compare --run --engines parakeetcpp-nemotron-streaming parakeetcpp-cpu parakeetcpp-vulkan whispercpp-vulkan-fa koboldcpp-whisper llamacpp-qwen-1.7b llamacpp-granite-5-2b audiocpp-qwen3 --budget 240`.

## Setup

- Execution context: `win32`, not elevated, no app container; Vulkan on device 0.
- Corpus: two saved synthetic English Kokoro clips (5.3 s and 11.45 s), two measured requests each
  after one warmup per engine, resident HTTP, load and warmup excluded.
- AudioCpp `0.9.4` Vulkan with the single-file `qwen3-asr-1.7b-q8_0.gguf` (2.47 GB, config and
  processor metadata embedded).
- llama.cpp Vulkan with `Qwen3-ASR-1.7B-Q8_0.gguf` plus its `mmproj` projector (2.52 GB together).
- AudioCpp session options: flash attention, packed projections, f16 KV, 256-token alignment, two
  offline chunks per batch. The spec's `cuda_perf` preset sets the same values but is CUDA-gated.

## Results

| Engine | Model | Median request |
| --- | --- | ---: |
| Parakeet CPP Vulkan 110M | `parakeet-tdt-ctc-110m-q8_0` | 0.087 s |
| Nemotron 3.5 streaming | `nemotron-3.5-streaming-q8_0` | 0.153 s |
| llama.cpp Granite Speech 5 2B | `granite-speech-5.0-2b-q8_0` | 0.186 s |
| llama.cpp Qwen3-ASR 1.7B (default) | `Qwen3-ASR-1.7B-Q8_0` | 0.184 s |
| Parakeet CPP CPU 110M | `parakeet-tdt-ctc-110m-q8_0` | 0.205 s |
| Whisper CPP Vulkan large-v3-turbo | `large-v3-turbo-q5_0` | 0.308 s |
| AudioCpp Qwen3-ASR 1.7B | `qwen3-asr-1.7b-q8_0` | 0.333 s |
| Kobold bundled Whisper | `large-v3-turbo-q5_0` | 0.582 s |

Evidence (../../output/asr/asr_resident_compare/unreviewed/1794453879199198100/artifacts/report.json).

## Streaming

Paced replay of the 5.3 s clip in 160 ms chunks, one warmup excluded:

| Engine | First text | Final after speech end |
| --- | ---: | ---: |
| AudioCpp Nemotron 3.5 | 0.99 s | 0.05 s |
| speech.cpp Qwen 0.6B, VAD | 1.19 s | 0.39 s |
| speech.cpp Qwen 0.6B | 1.36 s | 0.06 s |
| AudioCpp Qwen3-ASR, 3 s windows | 3.22 s | 0.10 s |
| llama.cpp Qwen3-ASR (default) | no partials | 0.18 s resident request |

Run: `python -m scripts.tests.cases.asr.shared.latency`; evidence
(../../output/asr/shared/latency/unreviewed/1794455126476096900/artifacts/report.json).

- llama.cpp answers `ws://host/v1/realtime` with a 101 upgrade, then refuses the first `session.update`
  with "The current model does not support realtime transcription", so the default recogniser returns
  text only after the utterance ends.
- AudioCpp streams it, but only when `audio_chunk_duration_sec` is set in the model config; its 30 s
  default window never closes on a short utterance, and the same value as a live-route query parameter
  is ignored.
- Window width trades latency against word boundaries: 2 s windows produce text at 2.21 s but split
  "practice a natural." / "conversation."; 3 s windows reach a clause boundary at 3.22 s and are kept.
- Partials arrive mid-utterance, so voice practice reads its first words about two seconds sooner on
  AudioCpp; end-of-utterance latency still favours llama.cpp.

## Outcome

- Both Qwen paths returned the same text on both clips: identical CER 0 and 0.007, the second from the
  corpus reference spelling `cafe` without the accent.
- AudioCpp is 1.8x slower than llama.cpp on the same model, so recognition stays on llama.cpp.
- Session tuning paid: 0.345 s untuned against 0.333 s tuned, faster on both clips; the tuned options
  are the profile's only configuration.
- AudioCpp's TTS advantage does not carry into ASR; the TTS pair is a different code path.

## Limits

- Two synthetic English clips. No noisy, accented, multilingual or long-form audio.
- Streaming covered one clip and one window per run, without a microphone.
- The conversions are separate but comparably sized files, so this is framework against framework.
- One build of each framework on one adapter.
