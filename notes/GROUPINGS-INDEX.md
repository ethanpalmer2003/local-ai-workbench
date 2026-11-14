# Groupings

Index only: it names the four kinds of grouping and the owner of each, and the values live in those files.

Four kinds of grouping answer four questions. **What is this?** is a label family, indexed below. **Where may it
live?** is placement, **when does it run and what may it start?** is the check/run taxonomy, and **how does a
session run?** is selection; each has one owner and is listed at the end rather than duplicated here.

A label is a closed set of values that a second file reads, so the two must agree. It does not matter whether it
crosses folders: `run outcome` stays inside one benchmark helper that every writer calls, and `catalog role` never
leaves the catalog. What makes either a family is that another file would otherwise restate the values.

A new family adds a row here and a constant beside its owner, and the
[vocabulary test](../scripts/tests/cases/shared/test_label_vocabulary.py) keeps both honest.

| Family | Applies to | Decides | Owner |
| --- | --- | --- | --- |
| Catalog category | catalog entries | Which model family an entry belongs to, and so which lookup and download scope reads it | `CATEGORIES` in [catalog.py](../scripts/config/models/catalog.py); the values are in [catalog.json](../scripts/config/models/catalog.json) |
| Catalog role | weight files | What a file is for | [catalog.json](../scripts/config/models/catalog.json) |
| Deferred | anything parked: a model, a framework, a build, a row, a runtime, a piece of work | What kind of thing it is, and what would unpark it | `DeferredKind` in [deferred.py](../scripts/config/shared/deferred.py); the records are in [deferred.yaml](../scripts/config/shared/deferred.yaml) |
| Delivery mode | speech clients | How text arrives: incremental, per segment, or once | [speech_delivery.py](../scripts/config/shared/speech_delivery.py) |
| Language tier | checkpoints | Which languages a model handles well | [model_languages.json](../scripts/config/models/model_languages.json) |
| Run outcome | saved run folders | Whether the evidence counts as a decision | [paths.py](../scripts/benchmarks/shared/paths.py) |
| Speech class | TTS weights and profiles | The speech floor a profile needs and a model declares | `SpeechClass` in [catalog.py](../scripts/config/models/catalog.py) |
| Test readiness | ASR profiles | What evidence a profile has | [coverage.py](../scripts/benchmarks/asr/coverage.py) |
| Test runner | ASR profiles | Which harness would test it | same |
| Workflow profile | defaults and benchmarks | Which speech, inference and media parts a framework must provide | `PROFILE_REQUIREMENTS` in [launcher_config.py](../scripts/launchers/launcher_config.py) |

## The other three kinds

- **Placement**: a component key picks the folder, a folder role says what may sit there, and a document role picks
  a page's home and word cap. One meaning per path, so no per-file label set exists.
  [folder rules](../.agents/FOLDERS.md), [document roles](../.agents/NOTES-CONVENTIONS.md).
- **Check and run**: a check level says how much a stage costs and when it runs, a suite and its live targets say
  what a test may start, and a capability row's budget class and section say how long its runner gets and which half
  of the matrix it belongs to. [checks](../.agents/CHECKS.md), `SUITES` in
  [native_suites.py](../scripts/tests/shared/native_suites.py), [capability_matrix.py](../scripts/tools/capability_matrix.py).
- **Selection**: a service mode, an engine or model choice, a service policy and the launcher's `--usage-profile` say
  how one session runs. Their values appear only where they are defined and imported, so no second file restates
  them. [launcher_config.py](../scripts/launchers/launcher_config.py), `USAGE_PROFILES` in the same file.

## Not a vocabulary

- **Row fields.** A capability row's deferral reason is a field of one owner's table; only the deferral concept is a
  family, because the parked-work page lists the same things.
- **Run status** (`completed`, `failed`, `passed`). Each writer sets its own today, so there is no agreed vocabulary
  to point at; outcome is the label that carries meaning.

## Principles

- A budget class is not a suite: capability rows are opt-in work with recorded evidence, while every test belongs to
  a suite by what it is allowed to start. Both are check/run, not labels.
- A page carries a role, not a label list: the role follows from its folder and basename, and the gate rejects a home,
  so the role table is shared from placement instead of being a family.
- A profile requirement is not a default: requirements say what a framework must offer, the shipped stacks say which
  models this workspace runs.
- Values stay in their owner: a constant when the set is fixed, a data file when the rows carry the value themselves
  (deferred records, catalog roles, language tiers), and this page only indexes which is which. A second
  machine-readable copy would drift from the constant that enforces it, and the owners are already importable.
- A page that does restate a data file's values names that file as the owner and is regenerated, never hand-edited; a
  page that merely explains the values is prose over the data, not a copy of it.
