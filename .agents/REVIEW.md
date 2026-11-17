# Review questions

Two lists. The first is answered by a command: if the section fails, the change is not done, and no one has to remember to look. The second needs a reader, and the move beside each question is what that reader does.

## A check answers these

| Question | Where it is answered |
| --- | --- |
| Is any function or class never referenced? | `=== DEAD CODE ===` in [dead_code.py](../scripts/review/checks/dead_code.py), which runs vulture |
| Is any import or local variable unused? | `=== LINT ===`: ruff `F401` and `F841` |
| Does an import have no declared dependency, or a dependency no import? | `=== DEPENDENCY HYGIENE ===`: deptry and the lock check |
| Is a file, folder or document in a role its home forbids? | `=== LAYOUT ===`, `=== DOCUMENTATION ===` |
| Is a label family unowned, or a family value written twice? | the label-family test in the suite |
| Is a link dead, a page over budget, or a pointer repeated? | `=== DOCUMENTATION ===` |
| Does a model id, path or alias no longer resolve? | `=== MODEL REFERENCE DRIFT ===` |
| Does every outbound HTTP call carry a timeout? | `=== NETWORK TIMEOUTS ===` |
| Is a module loaded by a name the source hides? | `=== DYNAMIC IMPORTS ===` in [dynamic_imports.py](../scripts/review/checks/dynamic_imports.py) |
| Is an assignment hidden in a comprehension? | `=== WALRUS OPERATOR ===` in [walrus.py](../scripts/review/checks/walrus.py) |
| Does anything outside the overlay resolve a local input path? | `=== OVERLAY ACCESS ===` |
| Do front-end ids, asset paths and injected keys still match? | `=== FRONT-END WIRING ===` |
| Is spelling, punctuation, a comment or the formatting right? | the text and formatting sections |
| Does the change keep its types and complexity limits? | `=== TYPE CHECK ===`, inventory |

## A reader answers these

| Question | Move |
| --- | --- |
| Standardized: one way per job, no second helper doing the same thing? | Search for the implementation before writing one; [code](CODE.md) names the generic homes |
| Redundant: the same job, constant, list or paragraph twice? | Compare the literal or the body, not the name; keep one and link the other |
| Reinventing a library? | Check the pinned dependency, then the stdlib; add the dependency and say what it was |
| Owned: one owner per procedure, choice and fact? | A second copy of a rule is a bug even when both copies agree |
| Grouped: does every value sit in one family with its owner? | [groupings](../notes/GROUPINGS-INDEX.md) indexes the families; a second place for a value is a defect |
| Bounded and visible: does every long operation have a budget and a heartbeat? | A wait takes a timeout and prints progress; a silent minute is a defect |
| Selected rather than hardcoded: ports, models, budgets, paths? | A literal in a branch is a defect; configuration owns the value |
| Is the evidence still true? | Rerun the command you cite; a number without its context is not evidence |

## When a question keeps needing a reader

A question that returns in review after review becomes a check, and leaves the second table. Dead code was one: the search took minutes and found eleven definitions, so the dead-code section answers it in under a second. Detection moved to vulture once a measurement showed this repository's own mention count missing the two real findings among 463 files; [dead_code.py](../scripts/review/checks/dead_code.py) keeps the policy that decides which of vulture's findings are actionable.

Report a finding with the file, the line and the move that fixes it.
