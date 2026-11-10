# Open questions

Decisions not yet made, grouped by area. Work that is already agreed lives in [TODO](TODO.md).

## Unresolved

- **Documentation similarity.** Measure duplicate or near-duplicate claims in the maintained Markdown. Open: which local embedding model (EmbeddingGemma-2 against Qwen3-Embedding-0.6B), which chunk unit (bullet, sentence, section), what cosine threshold, and whether a finding gates or only advises. The screen in the [TODO](TODO.md) answers the model and threshold; the gate decision waits for its false-positive rate.
- **Code similarity.** Whether embeddings add anything to code that clone detection and review do not. Duplication is a smaller risk there than in prose, so this waits until the documentation screen shows the model separates real duplicates from ordinary repetition.

## Resolved, revisit if needed

- **Hardware specs.** Machine numbers stay in the docs by decision; revisiting them is cheap but not planned.
- **Lint strictness.** The gate stays at the [code rules](../.agents/CODE.md) limit with no inline suppressions and ruff clean repo-wide. Tightening further (`ARG`, `PL`) is worth revisiting only if a defect slips through.
- **Embedding index over code and docs.** Declined for now: `grep` plus the owner rules answer the questions that azzfixture, an index needs its own refresh path and component key, and retrieval invites the paraphrased duplicates the one-owner rule prevents. Revisit if the document set grows past what reading a diff can hold. Duplicate detection is a different question, tracked under Unresolved.
- **Capability matrix evidence.** Decided: producers record what each run used, so a row is judged rather than guessed, and the flagged rows are refreshed by reruns tracked in the [TODO](TODO.md). Revisit if a producer stops writing provenance.

## Deferred

### OS limits

Windows is the only supported host, so anything that needs another operating system waits here rather than in the TODO, where it would sit as work that cannot start.

- **ExLlama-family engines.** hipfire and TabbyAPI with ExLlamaV3 need a Linux host with ROCm and EXL2/EXL3 weights rather than GGUF; the Windows sweep behind them was retired to `C:/AI/trash/retired-llm-inference-sweep`, and no model was downloaded for it. Validating them, including an MQ4/EXL3 conversion of the Swift checkpoint, waits on that host.
- **Nothing else is known to be blocked.** A test or launcher that names a platform limit adds the entry here with its evidence.

### Visibility

- **Visibility.** Both repositories stay private for now. A repository that was ever public is treated as leaked, so publishing remains the last step if it ever happens, not a decision that expires.
