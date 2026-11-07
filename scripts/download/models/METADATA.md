# Model metadata

Download public ASR quality/throughput tables with
`python -m scripts.download.models.asr_leaderboard`. It saves raw tables, the
local-only <=5B filter and provenance under generated ASR state. Selected immutable
CSV snapshots live in `scripts/tests/notes/asr/leaderboards-YYYY-MM-DD/`
for Git; weights and raw app configurations stay ignored. Snapshot refreshes
must use a new dated destination, preserving the old evidence.

Catalog identity: [models/catalog.json](../../config/models/catalog.json). Owner: [analyze_model.py](analyze_model.py). Inventory:
`C:/AI/scripts/state/shared/model_metadata.json`.

```powershell
C:/AI/bat/models/analyze_model_metadata.bat
C:/AI/bat/models/analyze_model_metadata.bat --hub --native
C:/AI/bat/models/analyze_model_metadata.bat --group asr audiocpp tts llamacpp
```

Offline inspection reads GGUF, safetensors and legacy Whisper headers, ONNX
metadata, adjacent JSON and the reviewed [language catalog](../../config/notes/MODEL-LANGUAGES.md).
No inference, pickle execution or remote model code. Missing downloads remain explicit.

`--hub` refreshes public cards/configs with resolved revisions, without weights.
`--native` uses verified metadata-only speech inspectors and records execution context.
Raw metadata and sourced summaries include languages/locales/dialects, tasks,
architecture, context, expert counts, quantization hints, tensor statistics,
sample rates, voices and capabilities where available.

Unknown is not unsupported. LLM text languages do not establish ASR coverage.
Conflicting claims remain separate; publisher claims do not establish accuracy.
Directory sidecars are marked as potentially ambiguous.

Large arrays are previews; `--full-arrays` retains arrays within safety limits.
`--tensor-index` adds tensor names/shapes/types, never weight payloads. Stored
elements are not active parameter counts.

`--model NAME` filters IDs/paths; `--path PATH` adds files/directories.
Partial scans preserve other entries. Unchanged headers are cached; `--refresh`
bypasses that cache. Previous inventories go to `C:/AI/trash/shared/model_metadata/`.
Source/inspector failures remain recorded.

Three evidence kinds stay separate: header/sidecar capabilities (`local`/`summary`),
`published_quality` from [model_quality.json](../../config/models/model_quality.json), and
`measured_metadata` from saved benchmark reports. Use `--measurements` to index
existing test reports, or pass report files/directories. This never runs tests.
Evidence retains framework commands, checkpoint hashes when recorded, context,
timing phases and measured counters. Missing RAM/VRAM stays unknown; weight-file
size is not runtime memory. Path matches do not revalidate current weight hashes.

Select ASR using per-language WER/CER, resident/streaming latency and measured
CPU/RAM/VRAM with the intended LLM/TTS active. Preserve dataset/version, decoding
mode, precision and source; leaderboard speed on other hardware is not local speed.
