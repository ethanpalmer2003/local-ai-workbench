# Qwen3-ASR 1.7B: AudioCpp against llama.cpp

Which framework should serve the recogniser? Same model, two conversions, one resident comparison and
one paced screen. Run the resident run with
`python -m scripts.benchmarks.asr.asr_resident_compare --run --budget 240`, the paced screen with
`python -m scripts.tests.cases.asr.shared.latency`.

## Setup

- `win32`, not elevated, no app container; Vulkan on device 0.
- Corpus: two saved synthetic English Kokoro clips (5.3 s and 11.45 s), two measured requests each
  after one warmup, load excluded.
- AudioCpp `0.9.4`: one 2.47 GB file carrying config and processor metadata. llama.cpp: 2.17 GB weights
  plus a 0.36 GB projector.
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

Paced numbers and the realtime-endpoint behavior live in [paced ASR latency](ASR-LATENCY.md), the owner
of every streaming measurement. Two consequences belong here:

- Language practice runs `audiocpp-qwen3` because it is the only measured streaming option here;
  Nemotron is faster but misheard English and could not transcribe Japanese, and NeMo exits at startup.
- Fixed windows rewrite punctuation at each boundary: the gateway smoke reads "help you. Practice a
  natural conversation". One-shot files keep llama.cpp's unbroken sentence.

## Outcome

- Both Qwen paths returned the same text: CER 0 and 0.007, the second from the corpus reference
  spelling `cafe` without the accent.
- AudioCpp is 1.8x slower per request, so one-shot transcription stays on llama.cpp; it is the only one
  of the two that streams.
- Session tuning paid: 0.345 s untuned against 0.333 s tuned, faster on both clips.
- AudioCpp's TTS advantage does not carry into ASR; that pair is a different code path.

## Limits

- Two synthetic English clips; no noisy, accented or long-form audio, and no microphone.
- Separate but comparably sized conversions, one build each, one adapter.
