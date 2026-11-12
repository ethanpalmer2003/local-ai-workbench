# Markdown

- This page covers document organization: a document's role decides its home and word cap, and the gate rejects a home the role forbids. `--roles` prints the counts.

| Role | Home | Cap |
| --- | --- | --- |
| root | repo root: `README.md`, `AGENTS.md` | large, 700 |
| hub | each folder's `README.md` | large, 700 |
| agent rule | `.agents/`, including skills | small, 300 |
| running list | index and status pages under `notes/` and `scripts/tests/notes/`; the rules name them | long, 1000 |
| generated page | output of a tool | long, 1000 |
| note | `notes/`, except the running lists | medium, 500 |
| review record | `notes/reviews/` | medium, 500 |
| component guide | a component folder or `scripts/tests/notes/`, uppercase name | medium, 500 |

- A document that matches no role fails, so a new kind edits this table rather than adding a rule.
- Uppercase basenames except `README.md`, `AGENTS.md`, `SKILL.md` and other tool-required names.
- Prefer documenting in the code: a name or comment that states the rule beats a paragraph.
- One owner per thing: a procedure, choice or fact is stated once, and every other mention links to it.
- Describe capability and the command, not instances: model ids, counts and versions stay in config.
- A component with measured settings has a `TUNING.md`; its README links the page instead of repeating it.
- `TODO.md` holds pending work; completed evidence belongs in test status/results.
- Test notes group by component when several belong together.
- Maintained non-test Markdown covers current behavior, decisions and pending work only.
- Download definitions stay in Python catalogs; docs link to them.
- American English throughout: `scripts/review/spellings.py` reports every British variant with its American form.
- Evidence is cited, not linked: untracked run output stays a plain path, because a clone must not carry dead links.
- Links are relative with forward slashes, angle-bracketed when a path holds a space, and an anchor must name a heading that exists.
