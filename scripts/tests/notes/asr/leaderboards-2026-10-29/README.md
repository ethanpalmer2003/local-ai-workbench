# Open ASR leaderboard snapshot - 2026-10-29

Downloaded 2026-10-29 06:10:04 UTC (00:10:04 America/Regina).
Source: [Open ASR leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard).
Exact request and timestamp: [provenance.json](provenance.json).

- [Filtered English results](english-local-under-5b.csv): 40 entries; local/open
  models, at most 5B reported parameters; default English dataset selection.
- `table-*.csv`: all seven initial public tables, including multilingual,
  long-form and private-set aggregates. Headers identify each table's scope.
- Source was the application's public Gradio API. Its backing dataset repository
  returned HTTP 401; no private dataset access was attempted.
- RTFx is reported throughput: audio duration divided by processing duration.
  It is not first-token latency, local AMD speed, or a memory measurement.
  Batch/runtime/hardware settings may differ across submissions.
- Parameter/language counts are leaderboard labels; Qwen's 52 combines languages
  and dialects. Use the reviewed model catalog for language lists.

Selected group: Qwen 1.7B-hf, Granite Speech 5.0 2B, Cohere Transcribe 2B,
Parakeet v3 0.6B, and Qwen 0.6B-hf. Native conversions are separate runtime
candidates; published accuracy is not proof of GGUF/runtime parity.

Immutable downloaded evidence intended for version control. Refresh into another
dated snapshot; do not replace this table with newer results.

## Brief local measurement

[Summary CSV](local-resident-summary.csv), [complete report](local-resident-report.json).
All five passed on RX 7800 XT Vulkan in normal Windows context (AppContainer=false,
administrator=false). Two saved English Kokoro clips, 5.3s/11.5s; three repetitions
each. Startup/loading/warmup excluded from request medians and retained separately.
No simultaneous LLM/TTS inference. Repeated prompts may benefit from runtime caches.

| Model/runtime | Median request | Sampled process GPU MiB | Resident RSS MiB |
| --- | ---: | ---: | ---: |
| Qwen 1.7B / llama.cpp | 192ms | 3749 | 1943 |
| Cohere 2B / AudioCpp | 116ms | 2398 | 2458 |
| Qwen 0.6B / speech.cpp | 117ms | 1187 | 141 |
| Parakeet v3 / parakeet.cpp | 102ms | 1096 | 119 |
| Granite 5.0 2B / llama.cpp | 171ms | 3704 | 1824 |

GPU counters captured only one sample per engine: observed lower bounds, not
reliable peaks. CPU/RSS samples are sparse too. Memory includes installed runtime
settings/buffers; file sizes are separate. Cohere requires explicit `en`, rejecting
`auto`; the final group uses explicit English throughout. Six requests cannot
establish p95 or robust speed rankings; these are compatibility/resource screens,
not new accuracy benchmarks. Full checkpoint hashes/settings are in the report.
