# Agent restrictions

What limits an agent in this workspace, what enforces each limit, and where the rule is written. The
enforcement and the prose are deliberately separate: a rule a hook enforces is listed here so a reader does not
have to find it in three trees. The whole list prints: `python -m scripts.review.restrictions`.

| Restriction | Enforced by | Written in |
| --- | --- | --- |
| No recursive scan of the weight, install and runtime roots | the `guard-deep-scan` profile plugin, which refuses the command before it runs | `runs/state/plugins/guard-deep-scan` (installed in the profile, not tracked) and [code search](CODE-SEARCH.md) |
| Search reads tracked files: `git grep`, `git ls-files`, or a graph tool, never a filesystem walk from the root | the same plugin plus the measured guidance | [code search](CODE-SEARCH.md) |
| The two code indexes are snapshots, so a commit refreshes them | `refresh-indexes` post-commit hook | [code search](CODE-SEARCH.md) |
| Formatting, lint, spelling, punctuation, the gate and the suite before a commit and before a push | `.pre-commit-config.yaml` hooks (`gate-scoped`, `suite-scoped`, `gate-full`, `suite-full`) | [checks](CHECKS.md) |
| The full section list and their levels: what fails, what warns | `python -m scripts.review` | [checks](CHECKS.md), [review](../scripts/review/README.md) |
| Framework installs, model downloads, deletion, persistent services and runs over five minutes need approval | the agent contract, read by the harness in `.agents/` | [AGENTS](../AGENTS.md) |
| A harness sandbox denial is a policy, not a bug: report it, never retry around it | the harness profile, and the workarounds recorded for it | [DeepSeek Harness](DEEPSEEK-HARNESS.md), [Codex](CODEX-HARNESS.md) |
| Low-integrity processes crash Electron apps, so the launcher label matters | the launcher, which checks the label before starting | [low integrity](ELECTRON-LOW-INTEGRITY-CRASH.md) |
| Personal terms must not reach the tree or the history | `public_audit`, run before publishing | [publish skill](skills/publish-repo/SKILL.md) |
| A directory's role decides what may live in it | the layout section of the gate | [folders](FOLDERS.md) |
| A tracked file past the host's per-file cap is refused before the push | the layout section's large-file guard | [layout](../scripts/review/checks/layout.py), [failures](FAILURES.md) |
| A failed step names its root cause and the guard that stops it repeating | the agent contract and the failure table | [failures](FAILURES.md) |
| No multi-line Python through `pwsh`, no content rewrite through PowerShell, no `git add -A` | the agent contract and the harness page; the push then proves the content | [failures](FAILURES.md), [DeepSeek Harness](DEEPSEEK-HARNESS.md) |
| One owner per fact | the gate's single-owner tokens and the review questions | [code](CODE.md), [review](REVIEW.md) |
| Only the newest run per capability case and the newest two gate reports survive; older regenerable evidence is pruned | `state_cleanup.prune_generated`, run at the end of every gate run | [retention](../scripts/tools/state_cleanup.py) |
| A handoff bundle needs a clean, current recorded full validation | the builder names the failed or stale stage and writes no bundle | [handoff](../scripts/review/handoff.py) |
| Live, slow and paid checks are opt-in; a TODO entry or a saved result never authorizes one | the agent contract | [checks](CHECKS.md) |
| A model is changed, moved or removed through `model_admin`, which edits the owning catalog, regenerates `ids.py`, rewrites references and trashes the weights | the agent contract, plus the catalog test | [tools](../scripts/tools/README.md) |

Two of these are harness-level rather than repository-level: the profile plugin and the file sandbox. They travel
with the harness, so a session that loads a different profile can walk the trees the guard protects; the
[open question](../notes/OPEN-QUESTIONS.md) about an operating-system backstop is that gap.
