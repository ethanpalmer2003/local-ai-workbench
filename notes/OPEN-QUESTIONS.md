# Open questions

Decisions not yet made, grouped by area. Work that is already agreed lives in [TODO](TODO.md).

## Publishing

- **Visibility.** The repo is private and history is already squashed to one root commit, then scrubbed of a personal name with `git filter-repo --replace-text` (2026-11-07). Flipping it public is deferred; a repo that was ever public is treated as leaked, so this is the last step, not the first.
- **Name and history scrub.** On 2026-11-08 all 99 commits were rewritten with `git filter-branch`: the old profile name became `character`, an unused browser front-end was dropped with its wiring, and every typographic dash outside the quoted corpus references became ASCII. `main` was force-pushed and the rewritten-away objects pruned locally; a clone made before that date must be re-cloned. GitHub can keep unreachable objects for a while, so a fresh clone is the only proof.

## Private data

- **Private overlay.** Personal material lives outside git in `data/input/` (or `AI_INPUT_DIR`), and public docs name only the variable. Whether that should become a second private repository is settled; what stays open is how much of the download machinery can be useful without it.
- **Voice manifest example.** The downloader takes its choices from `voice_sources.json`, so a fresh clone has no usable `--characters` values. A tracked, placeholder-only example would document the schema; a real one would publish voice ids.
- **Character catalog entries.** Four `koboldcpp/TheDrummer_*` models are tracked and named by the chat default and `KOBOLDCPP_MODELS`. They could move to `models.private.json`, but that allowlist and the default are code-owned today.

## Repository conventions

- **Hardware specs.** Machine numbers stay in the docs by decision; revisiting them is cheap but not planned.
- **Lint strictness.** The gate sits at McCabe 10 with no grandfathering left, and every other ruff rule is clean repo-wide. Whether to tighten further (`ARG`, `PL`, stricter McCabe) is open.

## Tooling

- **Embedding index over code and docs.** A local embedding model with retrieval could answer cross-cutting questions such as where a port is set or which page owns a rule, and it would read code and Markdown together. Against it: the repository is small enough for `grep` plus the owner rules, an index needs its own refresh path and a component key, and retrieval may invite paraphrased duplicates that the one-owner rule exists to prevent. Whether any of that is worth building is open.
