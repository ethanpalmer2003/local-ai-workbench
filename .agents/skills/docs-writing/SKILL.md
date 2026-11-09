---
name: docs-writing
description: Use when creating, editing, deleting or reviewing Markdown in C:/AI, when a fact seems to need a new document, or when doc checks flag links, budgets or duplicated rules. Covers owner selection, role placement and the checks to run.
---

# Write or change a document

Rules live in [NOTES-CONVENTIONS.md](../../NOTES-CONVENTIONS.md). This is the order to apply them; nothing
here restates a value that page owns.

1. **Find the owner.** Search existing documents and code first. One owner per procedure; every other mention becomes a link.
2. **Decide it is prose.** Names, ids, paths, defaults and counts stay in code or config; prose carries only decisions a reader cannot infer.
3. **Place it.** Use the role table for the home and the cap.
4. **Write short and link.** Describe capability and the command, not instances.
5. **Verify.** `python -m scripts.review.layout` and `python -m scripts.review.docs`, then confirm no deleted file or module is still named.
6. **Retire.** Nonempty obsolete files move to `C:/AI/trash` with provenance.

Report the outcome in the reply, not in a new document.
