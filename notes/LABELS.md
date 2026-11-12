# Labels

Three things classify work here, and they answer different questions. A **folder** decides where a file
may live. A document **role** decides a page's home and word cap. A **label** decides behavior: which
budget a capability row gets, which harness may test a profile, whether a saved run counts as a
decision. Only the last needs a vocabulary, and only because several files must agree on it.

Each owner below holds the values; this page names the families and links them, so a value is edited in
one place. A new family adds a row here and a constant beside its owner, and the
[vocabulary test](../scripts/tests/cases/shared/test_label_vocabulary.py) keeps both honest.

| Family | Applies to | Decides | Owner |
| --- | --- | --- | --- |
| Budget class | capability rows | Runner budget: seconds a row may take | [capability_matrix.py](../scripts/tools/capability_matrix.py) |
| Capability section | capability rows | Whether a row checks the shipped default or a challenger | same |
| Deferred | capability rows and parked work | Why a row is not judged and gets no rerun | same, indexed by [DEFERRED](DEFERRED.md) |
| Deferred kind | parked work | What kind of thing is parked, so a revisit condition makes sense | [DEFERRED](DEFERRED.md) |
| Suite | every test | Whether it may start a process or load weights | [test suite](../scripts/tests/README.md) |
| Workflow profile | defaults and benchmarks | Which speech, inference and media parts a framework must provide | `PROFILE_REQUIREMENTS` in [launcher_config.py](../scripts/launchers/launcher_config.py) |
| Tool group | non-user-facing helpers | Which model serves transcription or embeddings | `TOOL_DEFAULTS` in the same file |
| Media group | image and video | Which checkpoint or workflow carries a generation profile | `MEDIA_DEFAULTS` in the same file |
| Delivery mode | speech clients | How text arrives: incremental, per segment, or once | [speech_delivery.py](../scripts/config/shared/speech_delivery.py) |
| Speech class | TTS weights and profiles | The speech floor a profile needs and a model declares | `speech_class` in [catalog.json](../scripts/config/models/catalog.json) |
| Run outcome | saved run folders | Whether the evidence counts as a decision | [paths.py](../scripts/benchmarks/shared/paths.py) |
| Test readiness | ASR profiles | What evidence a profile has | [coverage.py](../scripts/tests/cases/asr/shared/coverage.py) |
| Test runner | ASR profiles | Which harness would test it | same |
| Language tier | checkpoints | Which languages a model handles well | [model_languages.json](../scripts/config/models/model_languages.json) |
| Catalog role | weight files | What a file is for | [catalog.json](../scripts/config/models/catalog.json) |
| Document role | pages | Home and word cap | [NOTES-CONVENTIONS.md](../.agents/NOTES-CONVENTIONS.md) |

## Not a label family

- **Folder.** Structure, not vocabulary: [folder rules](../.agents/FOLDERS.md) decide what may sit where.
- **Check level.** The gate's stages and their levels are a list, but they run in one order and read
  from one owner: [checks](../.agents/CHECKS.md).
- **Run status** (`completed`, `failed`, `passed`). Each writer sets its own today, so there is no
  agreed vocabulary to point at; outcome is the label that carries meaning.

## Principles

- A budget class is not a suite: capability rows are opt-in work with recorded evidence, while every
  test belongs to a suite by what it is allowed to start.
- A page carries a role, not a label list: the role follows from its folder and basename, so a second
  per-file label set would repeat it.
- A profile requirement is not a default: requirements say what a framework must offer, the shipped
  stacks say which models this workspace runs.
- Values stay in code. A second machine-readable copy would drift from the constant that enforces it,
  and the owners are already importable.
