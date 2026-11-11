# ASR benchmarks

Resident-speech measurements. Each runner starts the servers it needs, records provenance and
writes the shared report shape; the comparison table and its caveats live in
[MODEL-COMPARISONS](../MODEL-COMPARISONS.md).

- `asr_resident_compare.py` warms every configured resident ASR profile and times one clip.
- `whisper_embedded_compare.py` and `gemma_audio_compare.py` compare an embedded fixture against
  the standalone llama.cpp engine on the same weights.
- `audiocpp_drama3_offload.py` isolates AudioCpp speech while Drama3 holds VRAM.
- Measurement contract: [benchmark harness](../shared/benchmark.py); profile list:
  [ASR capabilities](../../launchers/asr/CAPABILITIES.md).
