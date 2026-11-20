# Handoff to a heavier model

`python -m scripts.review.handoff` writes a bundle under `scripts/state/generated/shared/handoff/<run>/` for a
model that should not read the tree. It exists because the prompt sent to a large model is expensive: the
mechanical findings already fail the gate, so they are not worth its attention, and the remaining questions
need judgment rather than a diff.

Two files:

- `HANDOFF.md` carries the rules that decide quality, the shape of the repository, where the weight sits per
  folder, and the files ranked by how much judgment they ask for: silent handlers, broad handlers, long
  functions and wide modules. It also holds the evidence the opt-in checks already produced - the duplicate
  pairs the baseline accepts, and the last `--code` similarity run with the date it ran.
- `REVIEW-REQUEST.md` is the instruction to give the heavier model: read the brief, then these files in full,
  answer these four questions, and leave the gate's own findings alone.
- `ast_map.json` holds every maintained Python file's public functions with their signature, span and whether
  they carry a docstring, so a reader can judge the shape without opening a file first.

The similarity block warns when the screen no longer describes the tree: past 25 changed files, older than
seven days (`STALE_CHANGES`, `STALE_DAYS`), or one pair naming a file or symbol the tree has since dropped.
The change count is recomputed from the manifest the report stored, because the report's own `changed_since_last`
counts what moved before that run instead. Either number is a reason to rerun that check rather than to trust
a pair count from another day.

The measurements are prompts, never findings: a silent `except` may be deliberate and a long function may be
one switch. A reader answers per file with line numbers, says which findings are real and which are
deliberate, and leaves the gate's own findings alone.

Ranking is `3 x silent handlers + broad handlers + 2 x long functions`, plus one for a module past twelve
public functions; `--ranked` sets how many files the brief names, and `--out` writes elsewhere. The
thresholds are `LONG_FUNCTION = 60` lines and `WIDE_SURFACE = 12` functions.

What this bundle deliberately does not do: run the similarity or duplicate checks (both are opt-in and slower
than a brief), or restate a rule that [code rules](../../.agents/CODE.md) own. It measures where a reader
should look and stops there.
