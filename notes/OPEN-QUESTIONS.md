# Open questions

Decisions not yet made, grouped by area. Work that is already agreed lives in [TODO](TODO.md).

## Unresolved

- None. New questions land here until they are answered or deferred.

## Resolved, revisit if needed

- **Character catalog entries.** The four tracked `koboldcpp/TheDrummer_*` weights moved to `models.private.json` on 2026-11-08. `KOBOLDCPP_MODELS` keeps a tracked fallback, so a clone without the overlay still starts the chat stack.
- **Voice manifest example.** A placeholder-only example is tracked and tested at `scripts/config/voice_sources.example.json`; no real id or source name is in it.
- **Private overlay.** Settled: personal material stays outside git as a second private repository, and the machinery is useful without it.
- **Name and history scrub.** Complete on 2026-11-08: 99 commits rewritten, `main` force-pushed, objects pruned, and a fresh clone used as the proof.
- **Hardware specs.** Machine numbers stay in the docs by decision; revisiting them is cheap but not planned.
- **Lint strictness.** The gate stays at McCabe 10 with no inline suppressions and ruff clean repo-wide. Tightening further (`ARG`, `PL`) is worth revisiting only if a defect slips through.
- **Embedding index over code and docs.** Declined for now: `grep` plus the owner rules answer the questions that azzfixture, an index needs its own refresh path and component key, and retrieval invites the paraphrased duplicates the one-owner rule prevents. Revisit if the document set grows past what reading a diff can hold.

## Deferred

- **Visibility.** Both repositories stay private for now. A repository that was ever public is treated as leaked, so publishing remains the last step if it ever happens, not a decision that expires.
