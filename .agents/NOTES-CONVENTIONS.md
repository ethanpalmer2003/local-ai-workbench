# Markdown

- A document's role decides its home and word cap, and the gate rejects a home the role forbids. `--roles` prints the counts.

| Role | Home | Cap |
| --- | --- | --- |
| root | repo root: `README.md`, `AGENTS.md` | large, 700 |
| hub | each folder's `README.md` | large, 700 |
| agent rule | `.agents/`, including skills | small, 300 |
| code rules | `.agents/CODE.md` | medium, 500 |
| running list | index and status pages under `notes/` and `scripts/tests/notes/`; the rules name them | long, 1000 |
| generated page | output of a tool, such as a matrix | long, 1000 |
| note | `notes/`, except the running lists | medium, 500 |
| review record | `notes/reviews/` | medium, 500 |
| component guide | a component folder or `scripts/tests/notes/`, uppercase name | medium, 500 |

- A document that matches no role fails, so a new kind edits this table.
- A page is generated only when it derives from evidence; a list already in a data file is not reprinted.
- Uppercase basenames except tool-required names such as `README.md`, `AGENTS.md` and `SKILL.md`.
- Prefer the code: a name or comment that states the rule beats prose.
- One owner per thing: state a procedure, choice or fact once, then link it.
- Describe capability and the command, not instances: ids and counts stay in config.
- A component with measured settings has a `TUNING.md` its README links instead of repeating.
- `TODO.md` holds pending work; completed evidence belongs in test status/results.
- Test notes group by component when they belong together.
- Maintained Markdown covers current behavior, decisions and pending work only.
- Download definitions stay in Python catalogs; docs link them.
- American English throughout: `scripts/review/spellings.py` reports every British variant with the American form.
- Evidence is cited, not linked: untracked run output stays a plain path, so a clone has no dead links.
- Links are relative with forward slashes, angle-bracketed for a path with a space, and an anchor must name a real heading.
