# Agent instructions - C:/AI

- First response in a session must begin exactly: LOCAL_AGENTS_MD_LOADED
- Read [README.md](README.md), [scripts/README.md](scripts/README.md), and the relevant guide.

## Concise output
- Short bullets; state each essential detail once. Explain only non-obvious behavior, decisions or required action.
- Close each reply with compact `#### Decisions` (one list of choices made and one-line answers) and `#### Questions` headings where applicable.
- Use text-safe `[OK]`, `[WARN]`, `[FAIL]`, `->`; bound searches and report truncation.

## Clarify before acting
- Ask at once when the request is ambiguous or assumes an invented detail; never guess intent to keep moving.

## Work and permissions
- Routine reads, Git status/diff/log, static checks and task-owned runs under five minutes are allowed.
- Get approval for package changes, pushes, deletion, persistent services and runs over five minutes; prior approval covers the agreed task and retries.
- Never create or edit issues, pull requests or discussions outside this account; upstream reports stay local drafts.
- Respect explicit test deferrals. Never infer permission for live tests from a TODO or saved result.
- Fix a defect in code already being touched, then and there. Record a larger unrelated fix as a TODO entry.
- Each invocation uses its current tool policy; earlier outside-sandbox approval does not change later defaults.
- Before native/GPU work, servers or process discovery, state execution context; check the token with `C:/AI/scripts/.venv/Scripts/python.exe -m scripts.launchers.runtime.execution_context` and record it with benchmark evidence.
- Before manual llama-server startup, check `launch_util.llama_server_running()`. Manage only processes a run started and never stop an unrelated session. Port policy: [shared launcher helpers](scripts/launchers/shared/README.md).

## Structure and safety
- Reuse one canonical component key wherever that component owns files; identity stays consistent across config, catalogs, tests and batches. Paths come from `project_config.component()`.
- [Folder rules](.agents/FOLDERS.md) own typed bindings, naming and the move checklist. Preserve model identity and shared assets through a move.
- Preserve nonempty data by moving it to `C:/AI/trash`; direct deletion is for empty files/directories only. Verify resolved move/delete paths stay within the intended workspace.
- Preserve existing work and evidence. `.gitignore` entries cover whole folders.
- Use uv and `C:/AI/scripts/.venv`; secrets are in `scripts/.env`, Hugging Face data in `data/huggingface/`.
- Codex under [.agents/CODEX-HARNESS.md](.agents/CODEX-HARNESS.md): a command refusal is a hard stop; report what must be allowed.
- Running under DeepSeek Harness: [.agents/DEEPSEEK-HARNESS.md](.agents/DEEPSEEK-HARNESS.md) covers its permissions, sandbox denials and the settled workarounds.

## Guides and checks
- One owner per procedure, implementation or document; every other mention links to it with an example. Budgets and the review list: [notes conventions](.agents/NOTES-CONVENTIONS.md).
- Run `python -m scripts.review.structure_docs` and allowed import/type checks after structural edits. Live, slow or paid checks are opt-in; model-free checks are the default.
- Detailed rules: [code](.agents/CODE.md), [checks](.agents/CHECKS.md), [skills](.agents/SKILLS.md).
