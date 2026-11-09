# Open questions

Decisions not yet made, grouped by area. Work that is already agreed lives in [TODO](TODO.md).

## Unresolved

- **ASR installs to retire.** nemo-speechcpp, FunASR and sherpa-onnx each keep a file engine but show no advantage over the AudioCpp Nemotron default, Parakeet.cpp or whisper.cpp. Which of the three to remove is open; CrispASR was retired on 2026-11-08 because it ran whisper.cpp's own weights.

## Resolved, revisit if needed

- **Character catalog entries.** The four tracked `koboldcpp/TheDrummer_*` weights moved to `models.private.json` on 2026-11-08. `KOBOLDCPP_MODELS` keeps a tracked fallback, so a clone without the overlay still starts the chat stack.
- **Voice manifest example.** A placeholder-only example is tracked and tested at `scripts/config/voice_sources.example.json`; no real id or source name is in it.
- **Private overlay.** Settled: personal material stays outside git as a second private repository, and the machinery is useful without it.
- **Name and history scrub.** Complete on 2026-11-08: 99 commits rewritten, `main` force-pushed, objects pruned, and a fresh clone used as the proof.
- **Hardware specs.** Machine numbers stay in the docs by decision; revisiting them is cheap but not planned.
- **Lint strictness.** The gate stays at McCabe 10 with no inline suppressions and ruff clean repo-wide. Tightening further (`ARG`, `PL`) is worth revisiting only if a defect slips through.
- **Embedding index over code and docs.** Declined for now: `grep` plus the owner rules answer the questions that azzfixture, an index needs its own refresh path and component key, and retrieval invites the paraphrased duplicates the one-owner rule prevents. Revisit if the document set grows past what reading a diff can hold.

## Deferred

### OS limits

Windows is the only supported host, so anything that needs another operating system waits here rather than in the TODO, where it would sit as work that cannot start.

- **ExLlama-family engines.** hipfire and TabbyAPI with ExLlamaV3 need a Linux host with ROCm and EXL2/EXL3 weights rather than GGUF; the Windows sweep behind them was retired to `C:/AI/trash/retired-llm-inference-sweep`, and no model was downloaded for it. Validating them, including an MQ4/EXL3 conversion of the Swift checkpoint, waits on that host.
- **Nothing else is known to be blocked.** A test or launcher that names a platform limit adds the entry here with its evidence.

### Visibility

- **Visibility.** Both repositories stay private for now. A repository that was ever public is treated as leaked, so publishing remains the last step if it ever happens, not a decision that expires.
