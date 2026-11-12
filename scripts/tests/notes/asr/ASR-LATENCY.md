# Paced ASR latency

One paced English replay after warmup per configuration: a 5.3 s saved Kokoro utterance sent in 160 ms
chunks at wall-clock speed. The lifecycle excludes server/model loading and Node transport startup;
requests include per-utterance setup and loopback transport, and no microphone, browser, LLM or TTS load
runs beside them. Execution context: neither AppContainer nor administrator.

## Explicit end-of-input

| Setup | First partial from replay start | Final after last clip samples |
| --- | ---: | ---: |
| AudioCpp Vulkan / Nemotron | 0.98 s | 54 ms |
| NeMo Vulkan / Nemotron | 1.00 s | 124 ms |
| speech.cpp Vulkan / Qwen 0.6B | 1.36 s | 62 ms |

AudioCpp finishes its chunked PCM upload; NeMo/Qwen receive an explicit commit. No silence timer is in
this column, NeMo endpointing sits at 10 s to prevent automatic commits, and differing lookahead
defaults mean no universal ranking.

## Automatic turn detection

speech.cpp/Qwen with Silero, threshold 0.5, padding 300 ms and silence 500 ms: first partial **1.19 s**,
final **357 ms after clip end**. The clip holds about **478 ms of trailing quiet**, so the final lands
roughly **834 ms after speech ends** by an amplitude marker that is not human-labeled. Pacing: 5.302 s
manual, 5.312 s automatic for 5.300 s of input.

AudioCpp/NeMo automatic-VAD turn timing was not measured. Parakeet's prebuilt CLI reads a complete WAV
and its HTTP example only accepts completed uploads, so paced incremental input needs a C API or native
adapter; no Parakeet value is invented.

## 2026-11-11: Qwen3-ASR on two frameworks

Same 5.3 s clip and pacing, one warmup excluded. AudioCpp decodes fixed windows; llama.cpp would need
its realtime socket.

| Engine | First text | Final after last clip samples |
| --- | ---: | ---: |
| AudioCpp Vulkan / Nemotron | 0.99 s | 0.05 s |
| AudioCpp Qwen3-ASR, 3 s windows | 3.22 s | 0.10 s |
| speech.cpp Qwen 0.6B, automatic VAD | 1.19 s | 0.39 s |
| speech.cpp Qwen 0.6B, explicit end | 1.36 s | 0.06 s |
| llama.cpp Qwen3-ASR | no partials | 0.18 s resident request |

Evidence (../../output/asr/shared/latency/unreviewed/1794455126476096900/artifacts/report.json).

- llama.cpp upgrades `ws://host/v1/realtime` and then refuses the first `session.update` with "The
  current model does not support realtime transcription", so this build cannot stream that model.
- AudioCpp streams Qwen3-ASR only when `audio_chunk_duration_sec` sits in the model config: the 30 s
  default never closes on a short utterance, and the value is ignored as a live-route query parameter.
- Window width trades latency against boundaries. 2 s windows reach 2.21 s but split "practice a
  natural." / "conversation."; 3 s windows reach a clause boundary at 3.22 s and the profile keeps them.
- NeMo crashed during startup and contributes no row.

## Evidence and reuse

- AudioCpp/NeMo screen (../../output/asr/shared/latency/unreviewed/1793234224629034500/artifacts/report.json).
- Corrected Qwen manual/VAD screen (../../output/asr/shared/latency/unreviewed/1793234392776741400/artifacts/report.json).
- The initial VAD screen crossed the clip/padding boundary inside one packet;
  its finalization anchor is superseded by the corrected screen above.
- `python -m scripts.tests.cases.asr.shared.latency`; `--engines` selects a subset. Native execution is
  explicit, Node needs no new package, and one persistent helper serves warmup and measured requests.

AudioCpp/Nemotron advances for incremental recognition; Qwen remains a viable VAD-turn alternative.
Repeat with learner accents, French/Spanish and longer pauses before fixing turn settings or claiming
stable percentiles.
