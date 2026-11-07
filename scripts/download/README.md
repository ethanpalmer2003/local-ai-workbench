# Downloads and model audit

- Models: [catalog](../config/models/__init__.py), [metadata analyzer](models/METADATA.md). Frameworks: [catalog](frameworks/update_config.py), [update guide](frameworks/UPDATES.md).
- Canonical component/path owner: `project_config.COMPONENTS`; model destinations derive through `model_destination()`.

```powershell
C:/AI/bat/models/download_models.bat --list
C:/AI/bat/models/download_models.bat --group asr --list
C:/AI/bat/models/download_models.bat --model asr/whispercpp/large-v3-turbo-q5_0 --download
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
- Input preparation tools live in `download/input/`; personal voice recordings/transcripts are supplied locally. [Onboarding](../../notes/ONBOARDING.md).
- `python -m scripts.download.input.get_tts_voices --transcribe` fills missing voice-reference transcripts with Qwen3-ASR 1.7B, reusing a matching service or stopping the one it starts.

Speech checkpoint language counts/lists: [offline catalog](../config/notes/MODEL-LANGUAGES.md).
