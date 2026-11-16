# What each check catches

One mistake per check, the line it prints, and the fix. Messages are quoted from runs on 2026-11-16 and
name the real file where the entry here is shortened; the runner prefixes each with `[FAIL]`.

| Check | Mistake | Prints | Fix |
| --- | --- | --- | --- |
| layout | a file in a folder no component owns | `Unregistered component folder: scripts/tests/cases/tools/x.py` | register the folder, or move the file under its component |
| owned_tokens | a second module spells a literal one module owns | `'--yes' appears in ...:16; owner is scripts/shared/consent.py` | call `consent.take(args)` |
| duplicates | a pasted block in a pair pylint did not know | `a.py <-> b.py: 2 block(s), baseline 1` | fold the block into one implementation, or review and `--update` |
| docs | a guide past its word cap | `scripts/tools/README.md: 738 words exceeds 700` | move the procedure to its owner and link it |
| ruff | an unsorted import block | `I001 Import block is un-sorted` | `ruff check --fix` |
| basedpyright | an argument of the wrong type | `Argument of type "tuple[str]" cannot be assigned to parameter "x"` | fix the annotation or the call |
| model_references | a runtime default no catalog model resolves | the label and the runtime that cannot resolve it | point the runtime at the catalog label |
| frontend_wiring | a DOM id a script reads but the page never defines | `page.html: unknown element id 'x'` | add the element or correct the id |
| inventory_code | an inline `# noqa` | `Inline suppression: scripts/x.py:12` | move the suppression into `pyproject.toml` |
| typography | an em dash or curly quote in shipped text | `notes/x.md:3: em dash` | use a comma or a plain hyphen |
| comments | a TODO marker or commented-out code | `x.py:12: marker comment (TODO ...)` | delete it and explain the work in the commit |
| spellings | a British spelling | `notes/x.md:3: behaviour -> behavior` | use the American form |
| dead_code | a function nothing references | `x.py:12: unused function 'y' (60% confidence)` | delete it |
| package_audit | an import with no declaration, or a stale lock | deptry names the package and the rule | declare it and run `uv lock` |
| network_timeouts | an HTTP call without `timeout=` | `x.py:12: HTTP call without a timeout` | pass a timeout |
| overlay_access | a module resolves the overlay path itself | `x.py: reads OVERLAY; call local_overlay instead` | call `local_overlay` |
| similarity | a renamed copy of a function | `0.99 x.py :: f <-> y.py :: g`, with the pair count | fold both into one owner |
| public_audit | a personal term, token or absolute path that must not ship | the file, the term and the rule | remove it before publishing |

Each check runs alone, for example `python -m scripts.review.layout`; the gate runs every one.
