# Labels

Each family decides one thing. The owner holds the values, so this page lists the vocabulary and links
instead of restating it; a new family edits this table and its owner together.

| Family | Values | Decides | Owner |
| --- | --- | --- | --- |
| Budget class | `smoke`, `probe`, `benchmark` | Runner budget for one row: 90, 300 or 900 s | [capability_matrix.py](../scripts/tools/capability_matrix.py) |
| Capability section | `defaults`, `alternatives` | Whether a row checks the shipped default or a challenger | same |
| Deferred | one reason per parked row | Why a row is not judged and gets no rerun | same, indexed by [DEFERRED](DEFERRED.md) |
| Suite | model-free, `launchers`, `backends` | Whether a test may start a process or load weights | [README](../scripts/tests/README.md) |
| Workflow profile | `character`, `language`, `coding`, `tool`, `image`, `video` | Which speech, inference and media parts a framework must provide | `PROFILE_REQUIREMENTS` in [launcher_config.py](../scripts/launchers/launcher_config.py) |
| Tool group | `transcription`, `embeddings` | Which model serves a non-user-facing helper | `TOOL_DEFAULTS` in the same file |
| Media group | `image`, `video` | Which checkpoint or workflow carries a generation profile | `MEDIA_DEFAULTS` in the same file |
| Delivery mode | `streaming`, `chunked`, `whole` | How text arrives: incremental, per segment, or once | [speech_delivery.py](../scripts/config/shared/speech_delivery.py) |
| Speech class | `none`, `fast-multilingual`, `voice-design` | What a TTS weight file declares it can serve | `speech_class` in [catalog.json](../scripts/config/models/catalog.json) |
| Run outcome | `verified`, `no-gain`, `inconclusive`, `superseded`, `unreviewed` | Whether a saved run counts as a decision | [paths.py](../scripts/benchmarks/shared/paths.py), [conventions](../scripts/tests/EXECUTION-AND-REPORTING.md) |
| Test readiness | `resident-validated`, `unreviewed`, `disabled`, `manual`, `migrated-not-rerun` | What evidence an ASR profile has | [coverage.py](../scripts/tests/cases/asr/shared/coverage.py) |
| Test runner | `resident_compare`, `file_diagnostic`, comparison modules, `none` | Which harness would test a profile | same |
| Language tier | `transcription_ready`, `broad_coverage`, `adaptation_required` | Which languages a checkpoint handles well | [model_languages.json](../scripts/config/models/model_languages.json) |
| Catalog role | `chat`, `coding`, `embedding`, `multilingual`, `projector` | What a weight file is for | [catalog.json](../scripts/config/models/catalog.json) |
| Document role | root, hub, agent rule, note, review record, component guide | Home and word cap of a page | [NOTES-CONVENTIONS.md](../.agents/NOTES-CONVENTIONS.md) |

- A budget class is not a suite: capability rows are long opt-in work with recorded evidence, while
  every test belongs to a suite by what it is allowed to start.
- A profile requires what its page cannot run without. The character stack may attach image generation
  (`--with-image` or `--image-on-demand`), but sd.cpp starts disabled, so that leg is optional and the
  image profile stays separate.
- A profile requirement is not a default: requirements say what a framework must offer, the two
  `SpeechWorkflowDefaults` stacks say which models this workspace ships, and the tool group carries the
  helpers nothing user-facing drives.
