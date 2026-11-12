# Qwen3-ASR 1.7B: AudioCpp against llama.cpp

Does the framework that serves Qwen3-ASR fastest change the default recogniser? Same model, two
conversions, one resident comparison.

Run: `python -m scripts.benchmarks.asr.asr_resident_compare --run --engines parakeetcpp-nemotron-streaming parakeetcpp-cpu parakeetcpp-vulkan whispercpp-vulkan-fa koboldcpp-whisper llamacpp-qwen-1.7b llamacpp-granite-5-2b audiocpp-qwen3 --budget 240`.

## Setup

- Execution context: `win32`, not elevated, no app container; Vulkan on device 0.
- Corpus: two saved synthetic English Kokoro clips (5.3 s and 11.45 s), two measured requests each
  after one warmup per engine, resident HTTP, load and warmup excluded.
- AudioCpp `0.9.4` Vulkan with `qwen3-asr-1.7b-q8_0.gguf`, sha256 `3bc2462eca3a...`, 2,473,017,600
  bytes - a single file with the config and processor metadata embedded.
- llama.cpp Vulkan with `Qwen3-ASR-1.7B-Q8_0.gguf` (2,165,034,944 bytes) plus
  `mmproj-Qwen3-ASR-1.7B-Q8_0.gguf` (355,709,344 bytes).
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

## Outcome

- Both Qwen paths returned the same text on both clips: identical CER 0 and 0.007, the second from the
  corpus reference spelling `cafe` without the accent.
- AudioCpp is 1.8x slower than llama.cpp on the same model, so recognition stays on llama.cpp.
- Session tuning still paid: the AudioCpp arm ran 0.345 s without it and 0.333 s with it, faster on
  both clips. The tuned options are the profile's only configuration.
- AudioCpp's TTS advantage does not carry into ASR; the TTS pair is a different code path.

## Limits

- Two synthetic English clips. No noisy, accented, multilingual or long-form audio, and no streaming
  request was measured.
- The two conversions are separate files of comparable size (2.47 GB single file against
  2.52 GB weights plus projector), so this is framework against framework, not a bit-identical pair.
- One build of each framework on one adapter.
