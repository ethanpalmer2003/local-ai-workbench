# Markdown

- Root README/AGENTS: navigation and critical rules. Feature procedures: beside owning code. Project plans/reviews/TODO: `notes/`; test-wide status: `scripts/tests/notes/`.
- Group test notes by component when several belong together (`scripts/tests/notes/asr/`, `scripts/tests/notes/audiocpp/`); keep cross-domain status at the notes root and avoid one-note folders.
- Prefer documenting in the code: a name or comment that states the rule beats a paragraph elsewhere. Write prose only for decisions a reader cannot infer, and never in two places.
- Describe capability and the command to run, not instances. Model ids, character/voice names and asset filenames stay in catalogs and overlay manifests; docs name the role that consumes them. One owner per rule, including code versus doc.
- One procedure owner; replace duplicate explanations with links. Keep commands, required actions, constraints and useful evidence.
- Budgets: guides <=500 words; detailed agent rules <=300; root AGENTS <=450. Third-party documents and immutable run evidence are excluded.
- Use uppercase Markdown basenames except `README.md`, `AGENTS.md`, `SKILL.md` and other tool-required names; `structure_docs` rejects anything else. Only README belongs directly at `scripts/tests/`.
- `TODO.md` owns pending work; completed evidence belongs in test status/results. Retire obsolete nonempty files to trash with provenance.
- Download definitions stay in Python catalogs; docs link to them. Update links and commands with path changes.

- Maintained non-test Markdown describes current behavior, decisions and pending work only. Keep code history/migration narratives out; preserve superseded text in trash. Test status/results own dated validation evidence.
