# Open questions

Running list for this repository. Nothing here is decided.

- **Visibility.** The repo is private and history is already squashed to one root commit. Flipping it public is deferred; a repo that was ever public is treated as leaked, so this is the last step, not the first.
- **Private overlay.** Personal material lives outside git in `data/input/` (or `AI_INPUT_DIR`), and public docs name only the variable. Whether that should become a second private repository is settled; what stays open is how much of the download machinery can be useful without it.
- **Voice manifest example.** The downloader takes its choices from `voice_sources.json`, so a fresh clone has no usable `--characters` values. A tracked, placeholder-only example would document the schema; a real one would publish voice ids.
- **Character catalog entries.** Four `koboldcpp/TheDrummer_*` models are tracked and named by the chat default and `KOBOLDCPP_MODELS`. They could move to `models.private.json`, but that allowlist and the default are code-owned today.
- **Hardware specs.** Machine numbers stay in the docs by decision; revisiting them is cheap but not planned.
- **Complexity baseline.** The lint gate sits at McCabe 10 and 28 functions are grandfathered behind `# noqa: C901` in `scripts/review/COMPLEXITY-DEBT.md`. Whether the tail is worth finishing is open; every other ruff rule is already clean repo-wide.
