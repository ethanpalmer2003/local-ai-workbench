# Failure modes

- Two kinds of blocker. A content failure (written code, a document, a generated file) is caught by the suite and the gate, so it blocks a commit or a push. A process failure (how a step is run, read or moved around the repo with) has no natural check, so it is recorded here with the symptom and its replacement.
- When a step fails, name its root cause before continuing, and add a deterministic guard when one exists. A rule alone is the fallback, never the first answer.

| Symptom | Root cause | Replacement |
| --- | --- | --- |
| A commit carries app-written state (logs, run scripts, connection configs) | `git add -A` stages whatever the tree contains | Stage explicit paths; the layout section's committed-index rule refuses an indexed file that matches an ignore rule |
| A committed file imports a module the repository does not have | `git add -u` stages modified paths only, so a new file stayed untracked while the edit that names it was staged | The layout section's committed-index rule refuses an import the index does not carry; still add the new path explicitly |
| A push is rejected for a file past the host limit | An exported bundle or patch was committed unchecked | The gate's `large files` section refuses a tracked file over [the limit](../scripts/review/checks/layout.py) before the push |
| A list keeps an entry that was meant to be removed | A line filter that silently matches nothing | Grep the text after the removal, and make the filter assert the count it expects before it writes; the gate cannot know the intent |
| A validation stage is stale the moment its run ends | The recorded fingerprint was captured before a stage updated what a later stage reads | `stage_runner.run(fingerprint_after=...)` re-reads each stage's inputs after it runs |
| A search walks `frameworks/` or `data/` for minutes, or is refused outright | A recursive scan named an ignored tree | Name one folder, `git grep` inside a checkout, or `python -m scripts.tools.locate_files SUFFIX` for a bounded depth under the model and framework roots |
| A `glob` pattern or a `-Recurse` listing inside `frameworks/`, `data/` or `scripts/state/` times out or is refused | The pattern matches at any depth, so naming an ignored tree is already the unbounded walk | Scope it to a tracked folder or use `git ls-files`; the refusal and [code search](CODE-SEARCH.md) name the bounded tool, and [the rules index](README.md) names every agent guide |
| A commit that a hook refused still reads as a success, and the new commit is missing | `git commit ...; git log` reports the exit code of the last command in the chain | Run the commit alone, or chain with `&&`, then confirm `git log --oneline -1` names the new commit |
| Every `pwsh` call costs 20-40 s | An unbounded glob or listing over the whole tree | `Select-Object -First N`, `-Name`, or scope the path to one folder |
| The same command re-run three times with the same failure | No root cause was named before the retry | Stop, read the message once, name the cause, then change the command |

- A failing call is not a repository defect: look for its class above before retrying, and add a row when none fits. A retry of the same command is not a fix.
- Harness-specific symptoms - sandbox denials, low-integrity labels, the 60 s foreground cap, heredocs, `python -c` quoting and a long silent run - stay in [the harness page](DEEPSEEK-HARNESS.md), which owns how this host behaves rather than how a step went wrong.
