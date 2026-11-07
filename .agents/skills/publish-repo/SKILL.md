---
name: publish-repo
description: Use when the user wants to make this repository public, clear or rewrite its git history, or split private inputs into another repo. Runs the audit first and refuses to publish anything still flagged.
---

# Publish the repository

Destructive and user-gated: start only when the user explicitly asks to publish or rewrite history.

## Before touching git

1. `C:/AI/scripts/.venv/Scripts/python.exe -m scripts.review.public_audit` must print `0 finding(s)`.
   A hit is fixed in the tree, never allow-listed to get past this step. Categories: `secrets`, `credentials`, `home-path`, `machine-path`, `private-word`, `private-input`, `large-file`, `ignored-tracked`.
2. Confirm personal data lives outside git: [local inputs](../../../scripts/config/notes/INPUTS.md) covers voices, characters, tone prompts, `models.private.json` and `defaults.json`; `--history` also scans every commit, and a hit there needs the rewrite below.
3. Back up history: `git bundle create C:/AI/trash/ai_launchers-<date>.bundle --all`.

## Rewrite and publish

1. Squash: `git checkout --orphan fresh`, stage the cleaned tree, one commit, `git branch -M main`.
2. Push with `--force-with-lease`; verify `git log --oneline | wc -l` = 1.
3. Fresh-clone check: clone to a temp folder and run the model-free suite, `scripts.review.structure` and the type check there.
4. Only then flip visibility. A repo that was ever public is treated as already leaked.

## Private side

- Optional second repo holds the `input/` tree unchanged; `AI_INPUT_DIR` points at it.
- The public repo names only the variable and the layout, never the private repo.

## Verify

- Audit clean again on the pushed tree; suite and structure green from the fresh clone.
