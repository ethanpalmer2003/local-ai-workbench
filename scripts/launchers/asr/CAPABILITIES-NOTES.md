# ASR capability notes

Counts, terminology and status that support the [ASR capabilities](CAPABILITIES.md) profile table.

Each installed engine or model variant is one profile. CPU/GPU variants are profiles, not different
recognition models. This groups the selected models, not every model each framework can run; the
[coverage ledger](../../benchmarks/asr/shared/coverage.py) enumerates them and owns test readiness,
while [screen results](../../tests/notes/asr/ASR-SCREEN.md) own measurements.

Streaming means stateful incremental recognition. Windowed/live utterance decoding
is different. VAD detects speech/silence; endpointing decides when a turn ends.
Neither implies streaming recognition. Any offline ASR can receive speech segments
from a shared external VAD; that integration is not automatically present.

[Paced English checks](../../tests/notes/asr/ASR-LATENCY.md) cover AudioCpp/NeMo/Qwen;
Parakeet CPU Nemotron now has a paced practice adapter; Sherpa pacing and physical microphone latency remain unverified. Upstream features may exceed
installed releases; optional features require version/asset checks before use.
