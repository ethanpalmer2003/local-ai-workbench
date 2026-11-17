# What each check catches

One mistake per check, the message template it prints, and the fix. Templates come from the checker's own
format string; the runner prefixes each line with `[FAIL]`. A row that names a tool instead of quoting a
template has its message in that tool.

| Check | Mistake | Prints | Fix |
| --- | --- | --- | --- |
| layout | a file in a folder no component owns | `Unregistered component folder: ...` | register the folder, or move the file under its component |
| owned_tokens | a second module spells a literal one module owns | `... appears in ...; owner is ...` | call the helper that owns it, such as `consent.take(args)` |
| duplicates | a pasted block in a file pair pylint did not know | `... block(s), baseline ...` | fold the block into one implementation, or review and `--update` |
| docs | a guide past its word cap | `... words exceeds ...` | move the procedure to its owner and link it |
| ruff | an unsorted import block | ruff names the rule and the line | `ruff check --fix` |
| basedpyright | an argument of the wrong type | basedpyright names the argument and its type | fix the annotation or the call |
| model_references | a runtime default no catalog model resolves | names the model label and the runtime that cannot resolve it | point the runtime at the catalog label |
| frontend_wiring | a DOM id a script reads but the page never defines | `... unknown element id ...` | add the element or correct the id |
| annotations | a five-part tuple spelled inline in a signature | `... atoms, depth ... union members` | name the record in a NamedTuple or dataclass |
| line_length | a wrappable line over 120 characters | `characters (` | wrap prose and code; templates and long tokens are exempt |
| inventory_code | an inline `# noqa`, or a folder over 20 direct files | `Inline suppression: ...` | move the suppression into `pyproject.toml`, or split the folder by purpose |
| typography | an em dash or curly quote in shipped text | `em-dash` | use a comma or a plain hyphen |
| comments | a TODO marker or commented-out code | `... marker comment (...)` | delete it and explain the work in the commit |
| spellings | a British spelling | `... -> ...` | use the American form |
| dead_code | a function nothing references | vulture names the definition, its line and the confidence | delete it |
| package_audit | an import with no declaration, or a stale lock | deptry names the package and the rule | declare it and run `uv lock` |
| network_timeouts | an HTTP call without `timeout=` | `... HTTP call without a timeout` | pass a timeout |
| overlay_access | a module resolves the overlay path itself | `... call local_overlay instead` | call `local_overlay` |
| similarity | a renamed copy of a function | names the pair, the score and the function names | fold both into one owner |
| public_audit | a personal term, token or absolute path that must not ship | names the file, the term and the rule | remove it before publishing |

Each check runs alone, for example `python -m scripts.review.checks.layout`; the gate runs every one. A new check
adds a row here, and the case module checks that the row exists and that its template still exists in the
checker.
