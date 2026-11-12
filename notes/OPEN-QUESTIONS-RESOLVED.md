# Resolved questions

Decisions that are settled, each kept for its reason and for what would reopen it. Undecided ones live in
[open questions](OPEN-QUESTIONS.md), and agreed work in [TODO](TODO.md).

- **Code similarity.** The 0.95 screen runs opt-in; it caught two near-identical ASR `start` functions and a loader switch that converted only the UNet node.
- **Hardware specs.** Machine numbers stay in the docs by decision; revisiting them is cheap but not planned.
- **Lint strictness.** The gate stays at the [code rules](../.agents/CODE.md) limit with no inline suppressions and ruff clean repo-wide. Tightening (`ARG`, `PL`) is worth it only if a defect slips through.
- **Embedding index over code and docs.** Declined for now: `grep` plus the owner rules answer what arises, and an index needs its own refresh path. Revisit if the document set outgrows a diff.
- **Capability matrix evidence.** Producers record what each run used, so a row is judged rather than guessed; flagged rows are refreshed through the [TODO](TODO.md) reruns.
- **Documentation similarity.** EmbeddingGemma-2 at 0.90 with the two-unit rule, opt-in and report-only. The current tree reports 40 pairs, all pointers, dated evidence or method statements. [Record](reviews/EMBEDDINGS-2026-11-10.md).
- **Catalog format.** [catalog.json](../scripts/config/models/catalog.json) stays JSON: it is edited through `model_admin`, ordered writes keep diffs stable, and validation runs on save. YAML would add only a comment beside each entry, which is not worth rewriting the writer. Revisit when entry comments matter more than stable diffs.
- **Lemonade voice design.** It stays a fast-multilingual framework, not a voice-design one. Its MOSS TTS entries are weaker than Breeze 2 for characters and too heavy for the language-practice setup, so neither profile needs a test and the Kokoro comparison was not run against them.
- **Framework-reported values.** Read live at the point of use, with no disposable index: the catalog label keys every read and a single model's detail view may read its packaged spec, about 60 ms per GGUF. `model_languages.json` stays because tracked pages must render with no weight installed; its AudioCpp `locales` are compared against the spec by the suite so a copy cannot drift, while the base-code list, tiers and sources beside them are judgment no model reports.
