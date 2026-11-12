# Open questions

Decisions not yet made, grouped by area. Work that is already agreed lives in [TODO](TODO.md).

## Unresolved

- **Which catalog fields mirror a framework.** [The rule](../.agents/CODE.md) forbids copying a fact a
  framework already exposes. It removed `speech_modes` (AudioCpp's spec answers preset versus clone)
  and `runtimes` (a GGUF loads in both; the one exception follows from the role). `speech_class` stays
  because no framework states a profile floor. Unaudited: `roles`, `in_use`, and AudioCpp options
  copied from packaged specs. Ask whether the framework can answer a field in place and whether the
  copy can disagree; settle one per review.
- **Catalog format.** [catalog.json](../scripts/config/models/catalog.json) is JSON although a person
  edits it through `model_admin`: ordered writes keep diffs stable, and every entry is validated on
  save. YAML would allow a comment beside each entry at the cost of rewriting the writer and the
  ordered-diff property. Convert only if entry comments are wanted more than stable diffs.

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

## Resolved, revisit if needed

- **Code similarity.** The 0.95 screen runs opt-in; it caught two near-identical ASR `start` functions and a loader switch that converted only the UNet node.
- **Hardware specs.** Machine numbers stay in the docs by decision; revisiting them is cheap but not planned.
- **Lint strictness.** The gate stays at the [code rules](../.agents/CODE.md) limit with no inline suppressions and ruff clean repo-wide. Tightening (`ARG`, `PL`) is worth it only if a defect slips through.
- **Embedding index over code and docs.** Declined for now: `grep` plus the owner rules answer what arises, and an index needs its own refresh path. Revisit if the document set outgrows a diff.
- **Capability matrix evidence.** Producers record what each run used, so a row is judged rather than guessed; flagged rows are refreshed through the [TODO](TODO.md) reruns.
- **Documentation similarity.** EmbeddingGemma-2 at 0.90 with the two-unit rule, opt-in and report-only. The current tree reports 40 pairs, all pointers, dated evidence or method statements. [Record](reviews/EMBEDDINGS-2026-11-10.md).

## Deferred

One index of everything parked: [DEFERRED](DEFERRED.md).

### OS limits

Windows is the only supported host, so anything that needs another operating system waits here rather than in the TODO, where it would sit as work that cannot start.

- **ExLlama-family engines.** hipfire and TabbyAPI with ExLlamaV3 need a Linux host with ROCm and EXL2/EXL3 weights rather than GGUF; the Windows sweep behind them was retired to `C:/AI/trash/retired-llm-inference-sweep`, and no model was downloaded for it. Validating them, including an MQ4/EXL3 conversion of the Swift checkpoint, waits on that host.
- **Nothing else is known to be blocked.** A test or launcher that names a platform limit adds the entry here with its evidence.

### Visibility

- **Repositories.** This repository is public since 2026-11-11; the overlay under `data/input/` stays out of git.
