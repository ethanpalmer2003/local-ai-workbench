# Supertonic 3 against Kokoro on AudioCpp

First timing pair for the practice TTS model and the Kokoro baseline it replaced. One sentence, one
Vulkan build, three measured requests after one warmup, WAV output.

Run: `python -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case supertonic --backend vulkan --samples 3`
and the same with `--case kokoro`.

## Setup

- Execution context: `win32`, process 22400 and 18728, neither elevated, no app container.
- Engine: AudioCpp `v0.9.4` Vulkan (`f7ac446f`, 2026-11-04), device 0 = RX 7800 XT.
- Text: "Good morning. How are you today?", `response_format=wav`, offline mode, one warmup excluded.
- Supertonic 3 Q8_0, voice `F1`, seed 1234, sha256 `9edd05cf92fe...`, 454,076,228 bytes.
- Kokoro 82M multilingual Q8_0, voice `af_heart`, seed 1234, sha256 `c6864b5b66e9...`, 932,617,696 bytes.

## Results

| Model | Startup | Warmup | Median request | Median audio | RTF | Peak process VRAM |
| --- | --- | --- | --- | --- | --- | --- |
| Supertonic 3 Q8_0 | 0.03 s | 0.91 s | 0.068 s | 2.53 s | 0.027 | 481 MiB |
| Kokoro 82M multilingual Q8_0 | 0.06 s | 5.57 s | 0.076 s | 2.30 s | 0.033 | 694 MiB |

Both models stream after the first request. Supertonic produced 44,100 Hz audio, Kokoro 24,000 Hz.

## Limits

- Startup time comes from the health endpoint, which answers before lazy loading; the warmup column
  carries the real model load.
- One English sentence, three samples, no listening comparison. Audio duration differs because the two
  models read at different rates, so RTF is the comparable figure.
- Peak VRAM is a lower bound from process counters on a shared adapter.
