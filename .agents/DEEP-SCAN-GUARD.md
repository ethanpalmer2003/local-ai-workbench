# Deep scan guard

A scan that would walk a local ignored tree is refused before it runs, because those trees hold hundreds of
thousands of files and the scan runs for minutes. The bundle is [harness/guard-deep-scan](../harness/guard-deep-scan/package.json);
the profile links it by path, so an edit reaches the next harness start, not the running one.

## What is excluded

The names come from the ignore files that already decide what is local, read once when the plugin loads:
`/data/`, `/frameworks/`, `/trash/`, `/.venv*/`, `/runs/benchmarks/`, `/.zed/`, `graphify-out/`,
`__pycache__/`, `.ruff_cache/`, `state/` and `runs/tests/` (the last two inside `scripts/`). A folder named
at the workspace root is heavy only there, which is why `scripts/download/frameworks` is readable source, while
a cache that repeats inside packages (`.git`, `.venv*`, `node_modules`, `__pycache__`, `.ruff_cache`) is heavy
wherever it appears. One hand-written list remains for that reason, and nothing else is copied.

## What is denied

- A `pwsh` or `bash` call with a recursive flag (`-Recurse`, `-rec`, `--recursive`, `find ... -name`, `du -a`)
  that names one of those trees.
- A recursive call rooted above them: the workspace root, `scripts`, `scripts/tests`, `scripts/benchmarks`
  and the absolute forms of those, because `scripts` holds all three run-output trees.
- A recursive flag with no root at all (`Get-ChildItem -Recurse`, `grep -r pattern`), which starts at the
  working directory, the workspace root. Naming a root, with `-Path` or a path, is what makes a scan bounded.
- A `glob` or `grep` whose `path` is inside one: both tools match at any depth, so naming the tree is
  already the recursive form.

Everything else passes: a listing of a specific folder, a command with no recursive flag, and a flag
written inside quotes, so documenting `-Recurse` in a file is not a scan. A specific file under a
refused tree is still readable with the read tool or `Select-String -Path`, which name one file rather
than a tree.

## What the denial says

The reason names the replacement and the guides: `python -m scripts.tools.locate_files SUFFIX` walks only the
configured roots to a fixed depth and answers in under a second, [code search](CODE-SEARCH.md)
lists the tool per question, and [the rules index](README.md) lists every agent document. Which trees the guard
treats as heavy, and whether anything else is as expensive, is `python -m scripts.review.tree_sizes --measure`.

## Limits

A guard can deny but cannot rewrite a command, so it must name the allowed form. It matches names in the
tool arguments, so an assembled path that never spells the tree name slips past, and the OS-level ACL weighed in
[open questions](../notes/OPEN-QUESTIONS.md) is the only rule no tool call can bypass.
