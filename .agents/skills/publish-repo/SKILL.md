---
name: publish-repo
description: Use when the user wants to make this repository public, rewrite its git history, or move local inputs out of it. Runs the audit first and refuses to publish anything still flagged.
---

# Publish the repository

Destructive and user-gated: start only when the user explicitly asks to publish or rewrite history.

## Before touching git

1. `python -m scripts.review --scrub` must print `0 finding(s)`. The scan is the overlay's
   `tools/private_audit.py`, which owns its categories and terms; a hit is fixed in the tree, never
   allow-listed to get past this step.
2. Confirm local inputs live outside git: [local inputs](../../../scripts/config/notes/INPUTS.md) covers the overlay layout and file names. The same scan without `--scrub` reads the tree only, and `--history` adds every commit, where a hit needs the rewrite below.
3. Back up history: the rewrite below writes its own bundle under `trash/` first.

## Rewrite

- `python data/input/tools/scrub.py rewrite` derives the rules from the overlay, writes them with
  plain LF, backs up, rewrites, re-adds the origin remote filter-repo removes, and fails when the
  tree id moved. Add `--invert PATH` for a file that must leave history; pass every historical path.
- `python data/input/tools/scrub.py verify` then compares the local and remote tree ids and runs the
  scrub again before a push.
- Or squash: `git checkout --orphan fresh`, stage the cleaned tree, one commit, `git branch -M main`.
- A force-push leaves old commits addressable by SHA on the host, and search caches what it indexed.
  Deleting the repository and recreating it under the same name is the only way to drop them; the
  token needs `delete_repo` (classic) or Administration write (fine-grained), and a 403 means it
  does not have it.

## Local inputs

- An optional second checkout holds the `input/` tree unchanged; `AI_INPUT_DIR` points at it.
- The public repo names the variable and the layout only.

## Verify

- Audit clean on the pushed tree and under `--history`; suite and structure green from a fresh clone.
