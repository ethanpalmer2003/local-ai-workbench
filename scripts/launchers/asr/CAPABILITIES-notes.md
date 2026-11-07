# ASR capability notes

Counts, terminology and status that support the [ASR capabilities](CAPABILITIES.md) profile table.

19 tracked profiles; 14 resident adapters. CPU/GPU variants are profiles, not
different recognition models. This groups our selected models, not every model
each framework can run. [Coverage ledger](../../tests/cases/asr/shared/coverage.py)
owns test readiness; [screen results](../../tests/notes/asr/ASR-SCREEN.md) own measurements.

Streaming means stateful incremental recognition. Windowed/live utterance decoding
is different. VAD detects speech/silence; endpointing decides when a turn ends.
Neither implies streaming recognition. Any offline ASR can receive speech segments
from a shared external VAD; that integration is not automatically present.

[Paced English checks](../../tests/notes/asr/ASR-LATENCY.md) cover AudioCpp/NeMo/Qwen;
Parakeet CPU Nemotron now has a paced practice adapter; Sherpa pacing and physical microphone latency remain unverified. Upstream features may exceed
installed releases; optional features require version/asset checks before use.
