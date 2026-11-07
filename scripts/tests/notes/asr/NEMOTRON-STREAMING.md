# Nemotron streaming runtime comparison

2026-10-28. AudioCpp Vulkan, NeMo-Speech.cpp Vulkan and Parakeet CPU all pass
true paced PCM recognition with shared Silero, Gemma E4B and Vulkan Kokoro.
Both llama.cpp and Kobold practice gateways pass for each runtime. CPU C API
library build is pinned to v0.6.1; the release CLI was not used as a paced adapter.

## Matched resource screen

One warmed English utterance per runtime, llama.cpp chat, same input and
700 ms silence/300 ms pre-roll, sequential runs. Startup/loading/warmup are
excluded. Partial timing begins with replay; final timing uses Silero's estimated
speech end, including silence detection and 128 ms gateway scheduling.

| Runtime | First partial | Final after speech end | Sampled process RAM peak | Sampled process VRAM peak |
| --- | ---: | ---: | ---: | ---: |
| AudioCpp Vulkan | 1.15 s | 1.09 s | 155 MiB | 1536 MiB |
| NeMo Vulkan | 0.92 s | 1.24 s | 150 MiB | 1236 MiB |
| Parakeet CPU | 1.15 s | 1.09 s | 1099 MiB | unavailable; CPU-only build |

AudioCpp's process includes **ASR and Kokoro**; the others' rows cover **ASR
only**, with Kokoro separate. These are not total-stack memory rankings.
Parakeet's sampled machine CPU peak was 41.8%, with eight native compute threads.
Its real Python worker PID was resolved within the owned launcher descendants;
the earlier redirector-only measurement is invalid for CPU/RAM and preserved.
GPU sampling is sparse and peaks are lower bounds. Missing counters are not zero.

The transcripts agree apart from punctuation. Parakeet's conversion emitted a
trailing locale token; the adapter removes it from displayed text and retains
`raw_text`. French/Spanish, learner accents, physical microphone/echo and stable
latency percentiles remain ungraded. Runtime conversions/lookahead may differ.

- [AudioCpp report](../../output/asr/shared/practice_smoke/unreviewed/1793244849940625700/artifacts/report.json)
- [NeMo report](../../output/asr/shared/practice_smoke/unreviewed/1793244869851308600/artifacts/report.json)
- [Parakeet worker report](../../output/asr/shared/practice_smoke/unreviewed/1793245036143686600/artifacts/report.json)
- [Both-gateway NeMo check](../../output/asr/shared/practice_smoke/unreviewed/1793244346730960300/artifacts/report.json)
- [Both-gateway CPU check](../../output/asr/shared/practice_smoke/unreviewed/1793244611283906800/artifacts/report.json)

Approved execution: AppContainer false, administrator false. Isolated ports;
only owned services stopped. No packages installed. Shared build logs/manifest
record the pinned source and compiler options. Release v0.6.1 remains latest;
no relevant stable Vulkan streaming fix was found, so that path remains disabled.

AudioCpp stays default: convenient ASR/Kokoro sharing, without a demonstrated
latency reason to switch. NeMo is a working GPU alternative; Parakeet CPU is
viable when keeping ASR off the GPU matters. [Setup](../../../launchers/asr/NEMOTRON-STREAMING.md).

Validation: 363 model-free regressions pass; type, structure/docs and code-size
checks pass; regression log in `scripts/state/logs/shared/nemotron-streaming-regressions-validated.log`.
The process-inspection fixture now uses the shared explicit psutil fixture; prior
failed checks remain preserved. Selection reasons live in the
[decision guide](../../../../notes/asr/ASR-EVALUATION.md).
