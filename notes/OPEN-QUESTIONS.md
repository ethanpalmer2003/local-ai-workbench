# Open questions

Decisions not yet made, grouped by area. Settled ones keep their reasons in [resolved
questions](OPEN-QUESTIONS-RESOLVED.md), and agreed work lives in [TODO](TODO.md).

## Unresolved

- **Where we store what a framework already reports.** The rule is to use the framework's answer
  rather than keep a copy ([code](../.agents/CODE.md)). Applied: `speech_modes` went, because AudioCpp's
  spec answers preset versus clone, and `runtimes` went, because a GGUF loads in both. Kept:
  `speech_class`, since no framework states a profile floor; `roles` and `in_use` state intent, which
  no model reports. The open part is selection: listing every clone-capable model should not mean
  querying each framework at request time. Two answers:
  - a disposable index keyed by catalog label, rebuilt when framework or model metadata changes, so a
    disagreement is a stale index rather than two authored truths; or
  - one query per page load, acceptable only for a single model's detail view.
  The index looks right for lists, the query for detail. Either way the key is the catalog label and
  the values reuse one vocabulary, so a stored copy and a live read cannot disagree on names. The two
  threads meet only for capability: `roles` and `in_use` are intent, so an index never answers them,
  while the AudioCpp option values are choices, not copies - the packaged spec declares the option
  names and this repository picks the values, so there is nothing to delete there.
  `model_languages.json` is the last candidate and mostly not a copy: the llama.cpp, Whisper and
  Parakeet GGUFs carry no language metadata, so the file is their only local source. Only its AudioCpp
  entries duplicate a packaged spec's `languages` array. Leave it until a view lists languages across
  models, and then read the AudioCpp entries from the spec and keep the file for the models that stay
  silent. A live spec read costs about 60 ms per GGUF.

## Superseded

A replacement is measured and clearly ahead while the older option still works and stays installed. An
entry leaves when that option is retired or the evidence stops holding, so a row here means "waiting to
be dropped", not "undecided".

- **Kokoro as the practice voice.** Supertonic 3 is ahead on request time, load time, VRAM and
  language count ([timings](../scripts/tests/notes/SUPERTONIC-TTS-SCREEN.md)). Kokoro stays because
  the Lemonade comparison pins its own `kokoro-v1`, it is the AudioCpp comparison baseline, and
  native Kobold speech still loads the Kokoro GGUF.
- **Piper and Sherpa TTS.** Retained alternatives with further work not planned
  ([note](../scripts/launchers/audiocpp/RETAINED-TTS.md)); they survive only for the resident
  benchmark.

## Deferred

One index of everything parked: [deferred.yaml](../scripts/config/shared/deferred.yaml).

### OS limits

Windows is the only supported host, so anything that needs another operating system waits here rather than in the TODO, where it would sit as work that cannot start.

- **ExLlama-family engines.** hipfire and TabbyAPI with ExLlamaV3 need a Linux host with ROCm and EXL2/EXL3 weights rather than GGUF; the Windows sweep behind them was retired to `C:/AI/trash/retired-llm-inference-sweep`, and no model was downloaded for it. Validating them, including an MQ4/EXL3 conversion of the Swift checkpoint, waits on that host.
- **Nothing else is known to be blocked.** A test or launcher that names a platform limit adds the entry here with its evidence.

### Model availability

- **Speech-to-speech models.** Not tested, and no open-weight candidate is known: the
  [comparison](https://artificialanalysis.ai/speech-to-speech) covers hosted systems, while a local candidate
  would have to fit the practice flow. Revisit when one appears; the practice stack speaks from text, so
  this would change the pipeline rather than a setting.

### Visibility

- **Repositories.** This repository is public since 2026-11-11; the overlay under `data/input/` stays out of git.
