# Markdown

- Only `README.md` and `AGENTS.md` sit at the root; every other document lives in `notes/`, including plans, reviews and lists. Feature procedures stay beside owning code; test-wide status goes in `scripts/tests/notes/`.
- Group test notes by component when several belong together (`scripts/tests/notes/asr/`); keep cross-domain status at the notes root and avoid one-note folders.
- Prefer documenting in the code: a name or comment that states the rule beats a paragraph. Write prose only for decisions a reader cannot infer, and never in two places.
- Describe capability and the command to run, not instances. Model ids, defaults, counts, versions and asset filenames stay in config, catalogs and overlay manifests; docs name the role that consumes them.
- One owner per thing: a procedure, an implementation choice or a fact is stated once, and every other mention links to it. Keep the commands and evidence a reader needs.
- Budgets: large 700 words, medium 500, small 300; each role picks one. Third-party documents and immutable run evidence are excluded.
- Use uppercase Markdown basenames except `README.md`, `AGENTS.md`, `SKILL.md` and other tool-required names; `structure_docs` rejects anything else. Only README belongs directly at `scripts/tests/`.
- A component with measured settings owns `TUNING.md`: what is in use, the evidence links, and what stays unmeasured. Its README links the page instead of repeating it.
- `TODO.md` owns pending work; completed evidence belongs in test status/results. Retire obsolete nonempty files to trash with provenance.
- Download definitions stay in Python catalogs; docs link to them and update both with a path change.

- Maintained non-test Markdown covers current behavior, decisions and pending work only. Keep migration narratives out; preserve superseded text in trash. Test status/results own dated evidence.

