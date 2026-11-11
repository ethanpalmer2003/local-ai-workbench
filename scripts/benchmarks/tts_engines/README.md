# TTS engine benchmarks

Resident speech-synthesis timing for the retained engines. `resident.py` starts one engine
server at a time and times the same text; `fixtures.py` holds the shared clips and voices so both
arms read identical input. Listening quality is not measured here.

- Results and the engine decision: [MODEL-COMPARISONS](../MODEL-COMPARISONS.md).
- Engine contracts: [AudioCpp TTS](../../launchers/audiocpp/README.md); report shape and
  provenance: [reporting](../shared/reporting.py).
