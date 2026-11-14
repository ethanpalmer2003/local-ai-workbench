# Labels

Index only: it names the owner of each label family, and the values live in those files.

Organization answers two questions. **Where may this live?** is structure: a component key picks the folder
and a [document role](../.agents/NOTES-CONVENTIONS.md) picks a page's home and word cap. **What does this
mean to the code?** is a label: a closed set of values that a second file reads, so the two must agree.

A label is not defined by crossing folders. `Run outcome` stays inside one benchmark helper that every
writer calls, and `catalog role` never leaves the catalog. What makes either a label is that a second
reader would otherwise restate the values.

Only a label needs a vocabulary, and only its values, because the owner below holds them. A new family adds
a row here and a constant beside its owner, and the
[vocabulary test](../scripts/tests/cases/shared/test_label_vocabulary.py) keeps both honest.

| Family | Applies to | Decides | Owner |
| --- | --- | --- | --- |
| Budget class | capability rows | Runner budget: seconds a row may take | [capability_matrix.py](../scripts/tools/capability_matrix.py) |
| Capability section | capability rows | Whether a row tests the defaults or the alternatives | `SECTION` in [capability_matrix.py](../scripts/tools/capability_matrix.py) |
| Catalog category | catalog entries | Which model family an entry belongs to, and so which lookup and download scope reads it | `CATEGORIES` in [catalog.py](../scripts/config/models/catalog.py); the values are in [catalog.json](../scripts/config/models/catalog.json) |
| Deferred | anything parked: a model, a framework, a build, a row, a runtime, a piece of work | Why it cannot start, what kind of thing it is, and what would unpark it | `DeferredKind` in [deferred.py](../scripts/config/shared/deferred.py); the records are in [deferred.yaml](../scripts/config/shared/deferred.yaml) |
| Suite | every test | Whether it may start a process or load weights | `SUITES` in [native_suites.py](../scripts/tests/shared/native_suites.py), with the live targets in [live_frameworks.py](../scripts/tests/cases/suites/live_frameworks.py) |
| Workflow profile | defaults and benchmarks | Which speech, inference and media parts a framework must provide | `PROFILE_REQUIREMENTS` in [launcher_config.py](../scripts/launchers/launcher_config.py) |
| Usage profile | every launcher's `--usage-profile` | Whether a session takes the GPU alone or shares it with another service | `USAGE_PROFILES` in [launcher_config.py](../scripts/launchers/launcher_config.py) |
| Delivery mode | speech clients | How text arrives: incremental, per segment, or once | [speech_delivery.py](../scripts/config/shared/speech_delivery.py) |
| Speech class | TTS weights and profiles | The speech floor a profile needs and a model declares | `SpeechClass` in [catalog.py](../scripts/config/models/catalog.py) |
| Run outcome | saved run folders | Whether the evidence counts as a decision | [paths.py](../scripts/benchmarks/shared/paths.py) |
| Test readiness | ASR profiles | What evidence a profile has | [coverage.py](../scripts/benchmarks/asr/coverage.py) |
| Test runner | ASR profiles | Which harness would test it | same |
| Language tier | checkpoints | Which languages a model handles well | [model_languages.json](../scripts/config/models/model_languages.json) |
| Catalog role | weight files | What a file is for | [catalog.json](../scripts/config/models/catalog.json) |
| Document role | pages | Home and word cap | [NOTES-CONVENTIONS.md](../.agents/NOTES-CONVENTIONS.md) |

## Not a label family

- **Folder.** The placement question above, with no vocabulary: [folder rules](../.agents/FOLDERS.md) decide
  what may sit where, and a path has one meaning.
- **Row fields.** A capability row's deferral reason is a field of one owner's table; only the
  deferral concept is a family, because the parked-work page lists the same things.
- **Check level.** The gate's stages and their levels are a list, but they run in one order and read
  from one owner: [checks](../.agents/CHECKS.md).
- **Selection setting.** `ServiceMode`, the engine and model choices and the service policies are closed sets, but
  their values appear nowhere except their own definition and the code importing it. A family's values are also
  written elsewhere, such as a data file, a batch flag, a stack declaration or a page, so an enum that only code
  names stays a setting.
- **Run status** (`completed`, `failed`, `passed`). Each writer sets its own today, so there is no
  agreed vocabulary to point at; outcome is the label that carries meaning.

## Principles

- A budget class is not a suite: capability rows are opt-in work with recorded evidence, while every
  test belongs to a suite by what it is allowed to start.
- A page carries a role, not a label list: the role follows from its folder and basename, so a second
  per-file label set would repeat it. The role table is shared because the gate must reject a home.
- A profile requirement is not a default: requirements say what a framework must offer, the shipped
  stacks say which models this workspace runs.
- Values stay in their owner: a constant when the set is fixed, a data file when the rows carry the value
  themselves (deferred records, catalog roles, language tiers), and this page only indexes which is which. A
  second machine-readable copy would drift from the constant that enforces it, and the owners are already importable.
- A page that does restate a data file's values names that file as the owner and is regenerated, never
  hand-edited; a page that merely explains the values is prose over the data, not a copy of it.
