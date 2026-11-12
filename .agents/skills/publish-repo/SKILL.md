---
name: publish-repo
description: Use when the user wants to make this repository public, rewrite its git history, or move local inputs out of it. Runs the audit first and refuses to publish anything still flagged.
---

# Publish the repository

Destructive and user-gated: start only when the user explicitly asks to publish or rewrite history.

## Before touching git

1. `python -m scripts.review.public_audit` must print `0 finding(s)`.
   A hit is fixed in the tree, never allow-listed to get past this step. Categories: `secrets`, `credentials`, `home-path`, `machine-path`, `ocabulary`, `input-name`, `large-file`, `ignored-tracked`.
2. Confirm local inputs live outside git: [local inputs](../../../scripts/config/notes/INPUTS.md) covers the overlay layout and file names. `--history` scans every commit, and a hit there needs the rewrite below.
3. Back up history: `git bundle create C:/AI/trash/local-ai-workbench-<date>.bundle --all`.

## Rewrite

- History-preserving: `python -m git_filter_repo --force --replace-text <rules>`, with the rules file outside the tree and one `term==>placeholder` line per term. Re-add the origin remote afterwards; filter-repo removes it.
- Or squash: `git checkout --orphan fresh`, stage the cleaned tree, one commit, `git branch -M main`.
- A force-push leaves old commits addressable by SHA on the host. Only deleting the repository removes them; making it private hides them, and recreating under the freed name also drops the rename redirect.

## Local inputs

- An optional second checkout holds the `input/` tree unchanged; `AI_INPUT_DIR` points at it.
- The public repo names the variable and the layout only.

## Verify

- Audit clean on the pushed tree and under `--history`; suite and structure green from a fresh clone.
