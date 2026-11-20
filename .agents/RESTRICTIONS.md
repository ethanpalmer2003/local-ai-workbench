# Agent restrictions

What limits an agent in this workspace, what enforces each limit, and where the rule is written. The
enforcement and the prose are deliberately separate: a rule a hook enforces is listed here so a reader does not
have to find it in three trees.

| Restriction | Enforced by | Written in |
| --- | --- | --- |
| No recursive scan of the weight, install and runtime roots | the `guard-deep-scan` profile plugin, which refuses the command before it runs | [package](../scripts/state/plugins/guard-deep-scan/package.json) and [code search](CODE-SEARCH.md) |
| Search reads tracked files: `git grep`, `git ls-files`, or a graph tool, never a filesystem walk from the root | the same plugin plus the measured guidance | [code search](CODE-SEARCH.md) |
| The two code indexes are snapshots, so a commit refreshes them | `refresh-indexes` post-commit hook | [code search](CODE-SEARCH.md) |
| Formatting, lint, spelling, punctuation, the gate and the suite before a commit and before a push | `.pre-commit-config.yaml` hooks (`gate-scoped`, `suite-scoped`, `gate-full`, `suite-full`) | [checks](CHECKS.md) |
| The full section list and their levels: what fails, what warns | `python -m scripts.review` | [checks](CHECKS.md), [review](../scripts/review/README.md) |
| Framework installs, model downloads, deletion, persistent services and runs over five minutes need approval | the agent contract, read by the harness in `.agents/` | [AGENTS](../AGENTS.md) |
| A harness sandbox denial is a policy, not a bug: report it, never retry around it | the harness profile, and the workarounds recorded for it | [DeepSeek Harness](DEEPSEEK-HARNESS.md), [Codex](CODEX-HARNESS.md) |
| Low-integrity processes crash Electron apps, so the launcher label matters | the launcher, which checks the label before starting | [low integrity](ELECTRON-LOW-INTEGRITY-CRASH.md) |
| Personal terms must not reach the tree or the history | `public_audit`, run before publishing | [publish skill](skills/publish-repo/SKILL.md) |
| A directory's role decides what may live in it | the layout section of the gate | [folders](FOLDERS.md) |
| One owner per fact | the gate's single-owner tokens and the review questions | [code](CODE.md), [review](REVIEW.md) |

Two of these are harness-level rather than repository-level: the profile plugin and the file sandbox. They travel
with the harness, so a session that loads a different profile can walk the trees the guard protects; the
[open question](../notes/OPEN-QUESTIONS.md) about an operating-system backstop is that gap.
