# Working rules index

Every session starts with [AGENTS.md](../AGENTS.md). Each subject below owns one question, so the root document
links here rather than restating a rule.

| Read when | Document |
| --- | --- |
| Writing or changing code | [CODE.md](CODE.md) |
| Choosing a check and its level | [CHECKS.md](CHECKS.md) |
| Looking for a symbol, a caller or matching text | [CODE-SEARCH.md](CODE-SEARCH.md) |
| Placing a component, its key, or making a move | [FOLDERS.md](FOLDERS.md) |
| Naming, sizing or placing a document | [NOTES-CONVENTIONS.md](NOTES-CONVENTIONS.md) |
| Reviewing finished work | [REVIEW.md](REVIEW.md) |
| Picking a skill | [SKILLS.md](SKILLS.md) |
| Reading an agent's hard limits | [RESTRICTIONS.md](RESTRICTIONS.md) |
| A step failed and would repeat | [FAILURES.md](FAILURES.md) |
| A DeepSeek Harness call was denied | [DEEPSEEK-HARNESS.md](DEEPSEEK-HARNESS.md) |
| A scan was refused before it ran | [DEEP-SCAN-GUARD.md](DEEP-SCAN-GUARD.md) |
| Running under Codex | [CODEX-HARNESS.md](CODEX-HARNESS.md) |
| Electron renders blank under Low integrity | [ELECTRON-LOW-INTEGRITY-CRASH.md](ELECTRON-LOW-INTEGRITY-CRASH.md) |

- A refused call names its guide instead of leaving a dead end: the deep-scan guard prints this index and
  [code search](CODE-SEARCH.md), so a scan into `data/`, `frameworks/`, `trash/` or `scripts/state/` reaches the
  bounded alternative rather than a retry.
- Skills sit under [skills](skills/), one `SKILL.md` each; [SKILLS.md](SKILLS.md) is their catalog.
