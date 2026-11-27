# Handoff to a heavier model

`python -m scripts.review.handoff` writes a bundle under `runs/state/generated/shared/handoff/<run>/` for a
model that should not read the tree: mechanical findings already fail the gate, so they are not worth its
attention, and the remaining questions need judgment rather than a diff.

## A passing full test comes first

The bundle is only written after the full validation has recorded a clean run, and the brief opens with that
run. `python -m scripts.tests.validate` (or [test_full.bat](../../bat/checks/test_full.bat)) updates the
frameworks, runs the gate and the model-free suite, then both live suites; about eleven minutes with live work
and two when they skip, with the per-stage ranges in [stage times](../config/shared/stage_times.py). The stage runner
writes `summary.json` beside the run's logs, and the handoff refuses to build when no run left one, when a
stage failed, or when the tree moved after the run.

The reviewer role and answer shape start from the [code-review skill](../../.agents/skills/code-review/SKILL.md), which
vendors obra/superpowers' prompt unedited; the request borrows the essentials for a bundle with no repository to open.
Two files:

- `HANDOFF.md` carries the rules that decide quality, the shape of the repository, where the weight sits per
  folder, the files ranked by how much judgment they ask for, and the full test behind the bundle. It also
  holds the evidence the opt-in checks already produced - the duplicate pairs the baseline accepts, and the
  last `--code` similarity run with the date it ran.
- `REVIEW-REQUEST.md` is the instruction: read the brief and the listed files, review them for quality from its own
  knowledge, and avoid the listed things - a blacklist, not a checklist of answers.
- `ast_map.json` holds every maintained Python file's public functions with their signature, span and whether
  they carry a docstring, so a reader can judge the shape without opening a file first.

- Only the newest two bundles stay: a bundle describes one tree, so the current review and the one it replaced are the whole history. `HANDOFF_KEEP` owns the number, and writing a third moves the oldest to trash. A bundle holding a file the builder did not write is kept.

The similarity block warns when the screen no longer describes the tree: past 25 changed files, older than
seven days (`STALE_CHANGES`, `STALE_DAYS`), or one pair naming a file or symbol the tree has since dropped.
The change count is recomputed from the manifest the report stored, because the report's own `changed_since_last`
counts what moved before that run instead. Either number is a reason to rerun that check rather than to trust
a pair count from another day.

The measurements are prompts, never findings: a silent `except` may be deliberate and a long function may be
one switch. How to answer them is in `REVIEW-REQUEST.md`.

Ranking is `3 x silent handlers + broad handlers + 2 x long functions`, plus one for a module past twelve
public functions; `--ranked` sets how many files the brief names, and `--out` writes elsewhere. The
thresholds are `LONG_FUNCTION = 60` lines and `WIDE_SURFACE = 12` functions.

It does not run the similarity or duplicate checks, both opt-in and slower than a brief, nor restate a rule
that [code rules](../../.agents/CODE.md) own.
