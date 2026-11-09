# Kokoro and heavier Piper screen

2026-10-28. One warmup and two measured English texts per setup. Approved normal
token: AppContainer false, administrator false. Native sessions were absent;
task-owned servers were cleaned up. No packages installed or defaults changed.

| Setup | Short seconds | Long seconds | Audio seconds short / long |
| --- | ---: | ---: | --- |
| AudioCpp CPU / Kokoro Q8_0 | 1.975 | 4.666 | 5.20 / 11.58 |
| Sherpa CPU / Kokoro v1.0 INT8 | 4.347 | 9.495 | 4.48 / 9.22 |
| Piper / Lessac high | 0.743 | 1.500 | 5.15 / 10.44 |

Kokoro: same af_heart voice, speed 1, five threads and identical texts. Sherpa's
pinned ONNX metadata confirms af_heart speaker ID 3. Different INT8/Q8_0
conversions, frontends and output durations prevent an exact model-equivalence
claim. AudioCpp timing includes HTTP/WAV return; Sherpa uses in-process C API
and excludes WAV saving. Neither measures streaming first-audio/playback.

Piper high is 113,895,201 bytes versus medium's 63,201,425, about 1.8x larger.
Its model card labels quality high; that is not a local listening verdict.
High RTF is 0.144 for both texts. The [medium screen](BRIEF-REALTIME-SCREEN.md)
used the same texts and recorded 0.122/0.262 seconds. Both Lessac voices are
English-only. More bytes do not make high a size/computation-matched Kokoro model.

## Evidence and reproducibility

- AudioCpp (../output/shared/kobold_embedded_compare/unreviewed/1793232624639086900/external/artifacts/results.json).
- Sherpa (../output/tts/shared/resident/unreviewed/1793232572040133000/artifacts/sherpa-onnx.json).
- Piper high (../output/tts/shared/resident/unreviewed/1793232601649332800/artifacts/piper.json).
- Model metadata/voice mapping in `scripts/state/logs/shared/tts-matched-provenance.log`.
- Models and ancillary files are pinned in the canonical download catalog.
  The resident runner accepts `--profile kokoro-v1.0-int8 --engine sherpa-onnx`
  or `--profile lessac-high --engine piper`; `--texts` reproduces the saved inputs.

AudioCpp advances over Sherpa for this CPU Kokoro speed screen. Piper high
remains viable for a higher-quality English option at low latency. Listening,
pronunciation, multilingual frontend/voice checks and active Gemma overlap are
ungraded. Sherpa's installed v2 API uses supplied lexicons/pre-phonemized input;
the downloaded English lexicon alone does not demonstrate French/Spanish support.

Implementation checks: eight catalog regressions pass; types and structure/docs pass.
