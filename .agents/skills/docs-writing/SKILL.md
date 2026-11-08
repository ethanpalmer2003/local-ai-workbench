---
name: docs-writing
description: Use when creating, editing, deleting or reviewing Markdown in C:/AI, when a fact seems to need a new document, or when structure checks flag links, budgets or duplicated rules. Covers owner selection, budget, instance names and the checks to run.
---

# Write or change a document

Rules live in [NOTES-CONVENTIONS.md](../../NOTES-CONVENTIONS.md). This is the order to apply them.

1. **Find the owner.** Search for an existing document or code location that already covers the topic (`grep`/`glob`, then read). One procedure owner; replace duplicates with links.
2. **Decide it is prose at all.** If the fact is a name, id, path, default or count, it belongs in code, JSON or config, and the document links to it. Prose carries decisions a reader cannot infer.
3. **Place it.** Only `README.md` and `AGENTS.md` sit at the root; every other document lives in `notes/`, except feature procedures beside the owning code and test status in `scripts/tests/notes/`.
4. **Write short.** Guides <=500 words, `.agents/` rules <=300, root AGENTS <=450. Describe capability and the command, not instances: no model ids, character or voice names, asset filenames.
5. **Link, do not restate.** Link the owner of a rule, the command that produces data, and the evidence that proves a claim.
6. **Verify.** `python -m scripts.review.structure` must report 0 issues; confirm budgets, link targets and that no deleted file is still referenced (`git grep <basename>`).
7. **Retire.** Nonempty obsolete files move to `C:/AI/trash` with provenance; empty files and folders may be deleted directly.

Report the outcome in the reply, not in a new document.
