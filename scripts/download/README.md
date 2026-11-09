# Downloads and model audit

- Models: [catalog](../config/models/__init__.py), [metadata analyzer](models/METADATA.md). Frameworks: [catalog](frameworks/framework_catalog.py), [update guide](frameworks/UPDATES.md).
- Canonical component/path owner: `project_config.COMPONENTS`; model destinations derive through `model_destination()`.

```powershell
C:/AI/bat/models/download_models.bat --list
C:/AI/bat/models/download_models.bat --group asr --list
C:/AI/bat/models/download_models.bat --group asr --download
C:/AI/bat/models/check_installed_models.bat --group asr
```

- Default lists only. Download requires explicit `--model` or `--active`; `--inactive` exposes optional/unknown-source entries.
- `in_use` selects restore downloads, not launcher defaults. Resolve missing provenance before downloading unknown entries.
- Group prefixes include all children: `asr`, or `asr/whispercpp`, `asr/llamacpp`, `asr/parakeetcpp` individually.
- Existing complete targets are skipped. HF transfers use the project token/cache; preserve credentials in `scripts/.env`.
- Curated non-Hub HTTPS assets require a pinned SHA256; verified downloads publish only after hashing. Failed partials are retained.
- `--range-download` uses verified authenticated ranges; `--resume-file PATH` requires one model and that mode. Preserve partials until validated/retired.
- Audit compares configured/runtime/catalog paths with installed files; unreferenced does not mean safe to delete. Shared/app-managed weights and missing optional models require interpretation.
- LLM weights share `models/llms/{coding_models,multilingual_models,character_models}`; runtime/model IDs stay stable. Gemma audio projectors stay beside their main weights.
- ComfyUI typed weights remain in `data/videogen`; Strata keeps its native pack/model layout. These are declared mappings.
- Downloaded benchmark tools stay in `frameworks/benchmarks`; owned runners stay in `scripts/benchmarks/`.
- `bat/models/download_models.bat` with no arguments fetches only the active files that are missing; it never looks for newer versions. `bat/models/update_models.bat` is the one that upgrades: it finds a higher version in a versioned family, downloads that file, rewrites references and moves the old weights to trash (`--dry-run` previews the swaps).
- `python -m scripts.download.models.updates` checks each in-use source against the Hub: a missing or unreachable pinned file fails, a size drift is reported, and a higher version token in the same family is a hint. Swapping to a newer release by hand is `model_admin replace OLD NEW --apply --download` after the new label exists in the catalog.
- Benchmark corpora: the tracked manifest in `config/benchmarks/language_corpus.json` pins the corpus revision and each clip's reference text; `python -m scripts.download.benchmarks.fleurs --download` fetches those clips into `data/benchmarks/corpora`. A changed manifest hash means new numbers are a new baseline.
- Input preparation tools live in `download/input/`; personal voice recordings/transcripts are supplied locally. [Onboarding](../../notes/ONBOARDING.md).
- `python -m scripts.download.input.get_tts_voices --transcribe` fills missing voice-reference transcripts with Qwen3-ASR 1.7B, reusing a matching service or stopping the one it starts.

Speech checkpoint language counts/lists: [offline catalog](../config/notes/MODEL-LANGUAGES.md).
