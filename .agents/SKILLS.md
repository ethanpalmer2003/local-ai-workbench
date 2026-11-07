# Project skills

- Format: one `skills/<name>/SKILL.md` per skill, YAML frontmatter `name` + `description`, then the body. The description is the trigger: it is the only part loaded before a harness decides to read the body.
- Loaded by: DeepSeek Harness (project root `.agents/skills`, rank 200 of `.dsh/skills`, custom dirs, `~/.dsh/skills`, `~/.agents/skills`) and Command Code 1.88+ (`.commandcode/skills`, `.agents/skills` at cwd or git root, plus the user-level pair; it also imports Claude Code `~/.claude/skills` and Gemini `<root>/skills`).
- Not loaded by harnesses without a skill loader. Codex is not installed here and shows no loader.
- This file sits beside `skills/` rather than inside it: Command Code warns about loose `.md` files in a skills root.
- Put outcomes in the skill, not restated documentation: a trigger, a decision order, and a link to the one owner doc.
- Always-true rules stay in `AGENTS.md`; reference material stays in `.agents/*.md`.

| Skill | Trigger |
| --- | --- |
| [deepseek-harness](skills/deepseek-harness/SKILL.md) | tool call denied, path write/delete fails, piped child fails, shell edit corrupted a file |
| [docs-writing](skills/docs-writing/SKILL.md) | create, edit or delete Markdown; a fact seems to need a new doc; structure flags links or budgets |
| [publish-repo](skills/publish-repo/SKILL.md) | make the repo public, rewrite history, split private inputs |
| [strata-tuning](skills/strata-tuning/SKILL.md) | make Strata faster, choose a profile, compare decode/prefill |
