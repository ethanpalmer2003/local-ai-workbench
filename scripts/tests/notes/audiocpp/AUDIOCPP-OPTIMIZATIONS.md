# AudioCpp optimization candidates

- Pending work: [TODO](../../../../notes/TODO.md). Candidate review dated 2026-10-22; RX 7800 XT, 16 GiB, Drama Q2/Breeze Q4_0. Native checks/official ROCm comparisons resumed 2026-10-27; [evidence](../../../../notes/NATIVE-VALIDATION.md).

## First: active Kobold-to-Drama baseline

- Compare 38/40 CPU expert layers, 2048 context, 4-second Drama playback buffer; hold voice/text/seeds/chunking fixed.
- Generate the full reply first, then send that exact text to TTS. Do not overlap LLM generation and speech synthesis.
- Warm up; separate loading/startup, queue time, first audio, synthesis rate and end-to-end completion. Record actual versus simulated underruns.
- Capture adapter/process VRAM, host RAM, timestamps and execution context; stop on failure. Preserve speech segments for later solo comparisons.

| Candidate | Scope / constraint |
| --- | --- |
| CPU threads / text segmentation | Compare completed Rocinante and Gemma replies. Larger segments may delay first speech |
| Expert cache / pinned experts | Drama MoE; compare bounded cache against CPU expert execution; check support, transfer counters and 32 GiB host headroom |
| Restricted output projection | Drama-specific installed implementation; end-to-end offload gain unestablished |
| `top_k=4097` stall fix | Drama sampling recommendation; do not copy into Breeze |
| Reference encoder chunking | Drama's Fish DAC; memory/time trade-off for long references |

- Breeze emission options are model-specific; playback buffering does not speed synthesis.
- After baseline: threads, then expert cache, then pinning and segment sizes, one change at a time with quality review.
- Upstream CUDA/RTX 5090 results do not predict AMD Q2 streaming gains. [Drama guide](https://github.com/0xShug0/audio.cpp/blob/main/docs/models/fish_drama3.md), [cache/pinning](https://github.com/0xShug0/audio.cpp/pull/927).
- [Historical outcomes](../OUTCOMES.md#drama-3-with-resident-rocinante) retain the retired idle-residency limitations.
