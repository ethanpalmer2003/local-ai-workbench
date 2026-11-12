# Open questions

Decisions not yet made, grouped by area. Settled ones keep their reasons in [resolved
questions](OPEN-QUESTIONS-RESOLVED.md), and agreed work lives in [TODO](TODO.md).

## Unresolved

- Nothing is unresolved. A decision that would change work is added here with its options.

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
