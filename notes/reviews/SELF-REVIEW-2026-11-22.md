# Self review - 2026-11-22

My own pass over the tree, against [code rules](../../.agents/CODE.md) and [review questions](../../.agents/REVIEW.md).
The gate covers mechanical findings; these are what a reader had to judge, with the fix that landed.

## Shared plumbing

1. `staleness.changed_since` ignored a removed file, so a similarity report kept describing a document the
   tree no longer had. It reports deletions now, and a tree fingerprint survives a file that vanishes mid-walk.
2. `resources.monitor_process` hid its own RAM-guard kill: the abort was in one sample, never in the summary a
   caller reads. The summary names `guard_abort` now.
3. `service_identity` crashed when a listening process exited between the port probe and `create_time`; a
   vanished pid is left out instead. `backends` keeps cleaning the rest when one process ignores its kill.

## Config and tools

1. `project_config` carried an always-empty `MODEL_ALIASES` and a consumer that could never run, plus an
   optional-`dotenv` branch for a declared dependency. Removed; `config.paths.load_json` refuses a non-object
   where the file is named.
2. `launcher_base` documented `LLAMACPP_CODING_BUILD` and `LLAMACPP_EMBEDDINGS_BUILD` as overrides while they
   were hard-wired `None`. They read the environment now, and an unknown build fails with its own message.
3. `model_admin --runtimes` was parsed and dropped; the flag is gone, and its path spellings use
   `shared.paths.display_path`.
4. `stage_runner` could hang past a stage cap when a child closed its output and kept running; the wait applies
   the same cap now. `refresh_index` duplicated its command loop and could fail a commit on a branch with
   no upstream. `probe_runner` killed only the launcher, not the tree holding the ports.
5. `low_integrity --fix` printed success whatever `icacls` returned. `local_work` read its archive relative to
   the current directory. `python_upgrade --install` ran `uv sync` against this project; it copies the project
   and lock into a scratch folder now.
6. `rename_path` rewrote a dotted name inside a longer one (`old_scripts.foo` for `scripts.foo`), so a rename
   could corrupt an unrelated import. Rewrite and leftover scan match whole names now.

## Integrity

1. `transfer.download` moved a Hub download into place after a size check only, even with a recorded `sha256`;
   it hashes the staged file first now. [TODO](../TODO.md) asks for the weights installed before this check.
2. `update_shared.replace_installation` moved the old install to trash and then copied, so a failed copy left
   nothing behind. It restores the previous install now; `trash.archive_path` returns where it put the path.

## Checks and runners

1. `network_timeouts` judged calls by the substring "timeout", so `timeout=None`, and a URL mentioning
   `timeout=30`, both passed. It parses the call now; two real unbounded calls and two chained-`.get` false
   positives appeared while validating the change.
2. `tests/run.py` reported a traceback when git failed. `model_run` could orphan a child
   when job binding failed, and returned a negative exit code.

## Deferred

1. Two import rewriters remain: `rename_path` and `rewrite_imports`. They overlap and the duplicate baseline
   records the shared block; merging them needs a behavior-parity pass first.
2. The llama.cpp profile runner still hand-rolls a server lifecycle where `trial.running_server` exists. It is a
   live-only path, so consolidating it needs a run that proves identical results.
3. `launcher_speech` hard-codes five catalog labels that `ModelId` names, against
   [models](../../scripts/config/models/README.md); the rename tool rewrites the strings, so it is consistent
   but not typed.
