# Failure modes

- Two kinds of blocker, and they live in different places. A content failure (written code, a document, a generated file) is caught by the suite and the gate, so it blocks a commit or a push. A process failure (how a step is run, read or moved around the repo with) has no natural check, so it is recorded here with the symptom and the replacement that stops it.
- When a step fails, name its root cause before continuing, and add a deterministic guard when one exists. A rule alone is the fallback, never the first answer.

| Symptom | Root cause | Replacement |
| --- | --- | --- |
| `Missing file specification after redirection operator` | A bash heredoc (`<<'PY'`) passed to PowerShell | Write the scratch script under `scripts/state/temp/` and run it, or use the file-edit tool |
| A file gains a literal `\r\n`, loses its line endings or fails to compile after a rewrite | Text replacement through PowerShell quoting, plus `Set-Content` rewriting CRLF | Rewrite with the edit tool or a Python script, then read `git diff` for that file |
| A commit carries app-written state (logs, run scripts, connection configs) | `git add -A` stages whatever the tree contains | Stage explicit paths, and check `git status --short` before the commit |
| A push is rejected for a file past the host limit | An exported bundle or patch was committed unchecked | The gate's `large files` section refuses a tracked file over [the limit](../scripts/review/checks/layout.py) before the push |
| A list keeps an entry that was meant to be removed | A line filter that silently matches nothing | Grep the text after the removal; the gate cannot know the intent |
| A validation stage is stale the moment its run ends | The recorded fingerprint was captured before a stage updated what a later stage reads | `stage_runner.run(fingerprint_after=...)` re-reads each stage's inputs after it runs |
| A search walks `frameworks/` or `data/` for minutes, or is refused outright | A recursive scan named an ignored tree | Name one folder, use the depth-bounded locator, or `git grep` inside a checkout |

- Harness-specific symptoms (sandbox denials, low-integrity labels, the 60 s foreground cap) stay in [the harness page](DEEPSEEK-HARNESS.md), which owns how this host behaves rather than how a step went wrong.
