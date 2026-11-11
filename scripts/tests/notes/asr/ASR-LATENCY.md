# Paced ASR latency

2026-10-28. One paced English replay after warmup per configuration. A 5.3-second
saved Kokoro utterance is sent in 160 ms chunks at wall-clock audio speed.
The shared lifecycle excludes server/model loading and Node transport startup.
Requests include per-utterance connection/session setup and loopback transport.
Approved token: AppContainer false, administrator false. Task-owned processes
were cleaned up. No microphone/browser capture or simultaneous LLM/TTS workload.

## Explicit end-of-input

| Setup | First partial from replay start | Final after last clip samples |
| --- | ---: | ---: |
| AudioCpp Vulkan / Nemotron | 0.98 s | 54 ms |
| NeMo Vulkan / Nemotron | 1.00 s | 124 ms |
| speech.cpp Vulkan / Qwen 0.6B | 1.36 s | 62 ms |

AudioCpp finishes its chunked PCM upload; NeMo/Qwen receive an explicit commit.
No silence timer is included in this finalization column. NeMo endpointing is
set to 10 seconds to prevent automatic commits within this isolated utterance.
Different model/conversion/chunk lookahead defaults remain; no universal ranking.

## Automatic turn detection

speech.cpp/Qwen with Silero, threshold 0.5, padding 300 ms and silence 500 ms:
first partial **1.19 s**, final **357 ms after clip end**.
The clip contains approximately **478 ms of trailing quiet**. Using its last
sample above amplitude 0.01 as an explicitly approximate speech-end marker,
the final arrives about **834 ms after speech ends**. The full transcript matches
the manual case. This heuristic marker is not human-labeled ground truth.
Measured clip pacing: 5.302 s manual, 5.312 s automatic for 5.300 s of input.

AudioCpp/NeMo automatic-VAD turn timing was not measured. Parakeet's prebuilt CLI
reads a complete WAV; its streaming-file results cannot measure paced incremental
input latency. Its HTTP example exposes completed uploads, so a paced C API/native
adapter is still needed. No Parakeet latency value is invented.

## Evidence and reuse

- AudioCpp/NeMo screen (../../output/asr/shared/latency/unreviewed/1793234224629034500/artifacts/report.json).
- Corrected Qwen manual/VAD screen (../../output/asr/shared/latency/unreviewed/1793234392776741400/artifacts/report.json).
- The initial VAD screen crossed the clip/padding boundary inside one packet;
  its finalization anchor is superseded by the corrected screen above.
- `python -m scripts.tests.cases.asr.shared.latency`; `--engines speechcpp` selects
  a subset. Native execution is explicit. Node's built-in HTTP/WebSocket support
  requires no new package; one persistent helper serves warmup/measured requests.
- Eleven model-free file/latency contracts pass; syntax, types and structure pass.

AudioCpp/Nemotron advances for incremental recognition; Qwen remains a viable
VAD-turn alternative. Repeat with learner accents, French/Spanish and longer
pauses before choosing turn settings or claiming stable percentiles.
