# Heavyweight review triage - 2026-11-21

Bundle `1795317801190382800`, reviewed by a heavier model against
[the request](../../scripts/review/HANDOFF.md). Findings, fixes and what stayed open. The full review is
`scripts/state/generated/shared/handoff/1795320229657952100/REVIEW-1795317801190382800.md`, cited rather than
linked because it is untracked evidence.

## Fixed

1. One trash owner. `state_cleanup.prune_trash` and `KEEP_TRASH_DAYS` are gone; `cleanup.prune_trash` deletes
   dated folders past `TRASH_DAYS`, and the gate calls it, so a `--state` run can no longer empty the trash.
   `scripts/config/trash.py` now exports `trash_root`, and the layout gate fails any other module that joins a
   `trash` path, which is the guard against a second owner returning.
2. `cleanup --outputs --keep N --older-than D` now reach `superseded`; the flags were parsed and dropped.
3. `superseded` lists a run once when both the age rule and the area cap name it.
4. Benchmark servers keep `config.build_env`: `trial.running_server`, `run_profile` and `overthink_profile`.
   `overthink_profile` also refuses an occupied test session, like `run_profile`.
5. `NativeModelSessions.start` and `ImageSessionPipeline.start` close what they started before re-raising.
6. `gpu_memory._get_windows_processes` reads psutil in-process instead of spawning a PowerShell WMI query on
   every poll; the three manual kill-and-wait blocks in `image_on_demand` use `launch_util.stop_process`.
7. One merged profile dictionary, `ALL_LLAMACPP_PROFILES`; five copies of the merge are gone.
8. `benchmark_ngram` reads and tokenizes the launcher tree once per token budget, not once per candidate.
9. `cleanup` uses `state_cleanup.path_size` and guards `iterdir`; `path_size` is a single `os.scandir` pass.
10. Removed `cleanup._report`, a bare `date.today()` expression, and two unused `cutoff` parameters.
11. `launch_process` binds the job through one `_bind_job` call.
12. `handoff` counts `except (Exception, ...)` and `contextlib.suppress` in its silent and broad handler tallies.
13. Extraction retention has one rule: newest twenty, never one younger than a day, so a running child keeps
    its extraction.

## Deferred

1. Entry-first ordering: [open question](../OPEN-QUESTIONS.md), because 135 modules put `main` last and 11 put it
   first, so the rule and the tree disagree.
2. Why dead code missed an unused helper: [TODO](../TODO.md), with the scoped-scan hypothesis.

## Not accepted

1. Routing every regenerate log to trash. Those files are rebuilt from a source of truth on the next run, so
   `state_cleanup` keeps deleting them; what it no longer does is touch the trash itself.
2. A gate rule against every `rmtree` or `unlink` call. Most call sites delete a file the module itself created,
   so the rule would need a list of nineteen allowed files, which is an allowlist rather than an invariant. The
   narrow trash-path rule covers the defect that mattered.
