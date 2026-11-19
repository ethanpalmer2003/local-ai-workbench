# Open questions

Decisions not yet made, grouped by area. Settled ones keep their reasons in [resolved
questions](OPEN-QUESTIONS-RESOLVED.md), and agreed work lives in [TODO](TODO.md).

## Unresolved

- **Public evidence for measured claims.** Forty tracked documents cite 132 artifact paths under the ignored
  `scripts/benchmarks/output/` and `scripts/tests/output/`, so a public reader cannot open the evidence behind
  a number. Options: commit a curated subset of the `report.md`/`summary.txt` files behind each decision, move
  the numbers into the documents themselves, or keep the paths local-only. The two folders hold 1.4 GB in total,
  so a wholesale commit is out; a curated set would be a few MB.
- **An operating-system backstop for the deep-scan rule.** The profile guard in
  `scripts/state/plugins/guard-deep-scan` refuses a scan under or above the ignored trees and derives those
  names from the ignore files, but it only binds harnesses that load that plugin. Options: an ACL that denies
  the agent process read access to `data/` and `frameworks/`, which no tool call can bypass and needs a fresh
  shell as the agent's user to prove; an ACL that allows only named subpaths, which is narrower but needs the
  same proof; or keep the guard as the only rule and accept that another harness can walk those trees. The
  first two change file permissions on 320 GB of installs, so the decision comes before any test.
- A decision that would change work is added here with its options.
- **How a run should be laid out on disk.** A run currently sits at `<root>/<area>/<case>/<outcome>/<epoch-id>/`, while the trash uses `YYYY-MM-DD` folders. Options: a date folder per run (`.../<outcome>/<YYYY-MM-DD>/<id>/`) so retention reads as calendar time and a whole day prunes at once; a build folder keyed on the engine commit (`.../<commit>/<id>/`) so a comparison across builds sits together and a superseded build is one folder; or keep the flat shape and let `cleanup.py` own the rule, which is what happens today. Cost of either change: every new run path moves, historical paths keep their current place because a tracked document may cite them, and a cited run id keeps working either way because the id does not change.


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
