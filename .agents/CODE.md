# Code

- Direct flow; a helper owns reused behavior, a class owns state, settings or policy.
- Functions stay within depth 4 and 100 lines; extract by responsibility. Preserve unexpected tracebacks.
- Keep lifecycle (`Startup`, `Request`, `StartupRequest`) and scope (`Generic`, `Shared`) explicit in settings classes; name mode-specific values.
- Preserve external keys, flags and IDs. Fix a contract at its source instead of a cast or suppression.
- Suppressions live only in `pyproject.toml` (`ignore`, `per-file-ignores`), each with a one-line reason. No inline `# noqa`: restructure, then ignore the narrowest file glob. `RUF100` and the review gate reject both stale and inline annotations.
- Shared path/model/proxy defaults live in configuration; orchestration-only switches stay local.
- Signatures and calls stay single-line up to 120 characters; pass-through arguments go last.
- Pick defaults from measured evidence and keep the caveats and execution context with them.
- ComfyUI tuning: screen square-equivalent 480 before 640, match cache and monitoring, report decode plus total time.

## Imports and paths

- Import heavy or optional dependencies only where they are used; keep python-dotenv optional.
- Import `project_cfg` from `config/project_config.py` and backend settings as `cfg` from `launchers/launcher_config.py`; reference them module-qualified.
- Derive paths from canonical roots and create directories explicitly. Write generated image bytes straight to the target file.

## Execution

- Run modules as `scripts.*` from `C:/AI`; wrappers set the working directory.

## Checks

- Run the allowed type/import/path checks and the focused regressions. Do not broaden a passing check without a reason; respect test deferrals.
