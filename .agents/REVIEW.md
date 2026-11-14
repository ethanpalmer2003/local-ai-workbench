# Review questions

A review answers these ten questions in this order, against the change and the code it touches. The gate answers what code can answer; the rest is a judgment pass with the move named beside the question.

| Question | Answer with |
| --- | --- |
| Is it standardized: one way per job, no second helper that does the same thing? | Search for the second implementation before adding one; [code](../.agents/CODE.md) names the generic homes |
| Is anything redundant: the same job, constant, list or paragraph in two places? | Compare the literal or the body, not the name; keep one, link the other |
| Is it grouped: does every value live in one family with its owner? | [groupings](../notes/GROUPINGS-INDEX.md) indexes the families; a value written in a second place is a defect |
| Does it reimplement a library? | Check the pinned dependency for the job first, then the stdlib; add the dependency and say what it was |
| Is it owned: one owner per procedure, choice and fact? | A second copy of a rule is a bug even when both copies agree |
| Is it placed right: folder role, component key, document role? | [folders](FOLDERS.md) owns placement; [markdown](NOTES-CONVENTIONS.md) owns document roles |
| Is any of it dead: unreferenced code, a rule for a path that no path uses, a skip with no criterion? | Grep the name across `scripts`; a definition with no caller is deleted, not commented |
| Is every long operation bounded and visible? | A wait has a budget and a heartbeat; a step over a few seconds prints what it is doing |
| Is every choice selected rather than hardcoded? | Ports, models, budgets and paths come from configuration; a literal in a branch is a defect |
| Is the claim evidence-backed, and is the evidence still true? | Run the command you cite; a number without its context is not evidence |

## How the gate already answers some of it

- Standardized within a file: complexity, unused imports and dead names (`python -m scripts.review`).
- Redundant dependencies and imports: dependency hygiene, which reads the pins.
- Grouped: the label-family test fails on a value that has no owner.
- Owned and placed: layout and documentation checks, plus the repeated-pointer warning.
- Visible: the review records and [test status](../scripts/tests/notes/STATUS-INDEX.md) name what ran.

Report a finding with the file, the line and the move that fixes it. A question that keeps returning gets a check, not a note.
