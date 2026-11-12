# Paced ASR latency evidence

Why each framework behaves as its numbers show, where the runs live, and how to repeat a screen. The
measured tables are in [paced ASR latency](ASR-LATENCY.md).

## Framework behavior

- llama.cpp upgrades `ws://host/v1/realtime` and then refuses the first `session.update` with "The
  current model does not support realtime transcription", so this build cannot stream that model.
- AudioCpp streams Qwen3-ASR only when `audio_chunk_duration_sec` sits in the model config: the 30 s
  default never closes on a short utterance, and the value is ignored as a live-route query parameter.
- Window width trades latency against boundaries. 2 s windows reach 2.21 s but split "practice a
  natural." / "conversation."; 3 s windows reach a clause boundary at 3.22 s and the profile keeps them.
- NeMo crashed during startup and contributes no row.
- AudioCpp/NeMo automatic-VAD turn timing was not measured. Parakeet's prebuilt CLI reads a complete WAV
  and its HTTP example only accepts completed uploads, so paced incremental input needs a C API or native
  adapter; no Parakeet value is invented.

## Evidence

- AudioCpp/NeMo screen (../../output/asr/shared/latency/unreviewed/1793234224629034500/artifacts/report.json).
- Corrected Qwen manual/VAD screen (../../output/asr/shared/latency/unreviewed/1793234392776741400/artifacts/report.json).
- Qwen3-ASR on both frameworks (../../output/asr/shared/latency/unreviewed/1794455126476096900/artifacts/report.json).
- The initial VAD screen crossed the clip/padding boundary inside one packet; its finalization anchor is
  superseded by the corrected screen above.

## Repeating

`python -m scripts.tests.cases.asr.shared.latency`; `--engines` selects a subset. Native execution is
explicit, Node needs no new package, and one persistent helper serves warmup and measured requests.

AudioCpp/Nemotron advances for incremental recognition; Qwen remains a viable VAD-turn alternative.
