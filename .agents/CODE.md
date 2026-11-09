# Code

- Direct flow; a helper owns reused behavior, a class owns state, settings or policy.
- Functions stay at McCabe complexity 10 or below; extract by responsibility. Preserve unexpected tracebacks.
- Keep lifecycle (`Startup`, `Request`, `StartupRequest`) and scope (`Generic`, `Shared`) explicit in settings classes.
- Preserve external keys, flags and IDs. Fix a contract at its source instead of a cast or suppression.
- Suppressions live only in `pyproject.toml`, each with a one-line reason; an inline `# noqa` is rejected, so restructure and ignore the narrowest glob.
- One supported way per job. No second installer, runner or format "just in case": uv is the only package manager, `uv.lock` the only resolution.
- Shared path/model/proxy defaults live in configuration; orchestration-only switches stay local.
- Signatures and calls stay single-line up to 120 characters; pass-through arguments go last.
- ASCII punctuation only: `scripts/review/typography.py` rejects dashes, curly quotes, ellipsis and no-break spaces.
- Pick defaults from measured evidence, keeping the caveats and execution context with them.

## Imports and paths

- Import heavy or optional dependencies only where they are used; keep python-dotenv optional.
- Dependencies stay as new as every dependent allows. Read the constraint from `dist-info`, re-lock with uv, and delete pins nothing imports.
- Import `project_cfg` from `config/project_config.py` and backend settings as `cfg` from `launchers/launcher_config.py`; reference them module-qualified.
- Derive paths from canonical roots and create directories explicitly. Write generated image bytes straight to the target file.

## Execution

- Run modules as `scripts.*` from `C:/AI`; wrappers set the working directory.
- PowerShell uses absolute forward-slash paths and an explicit working directory.
- Run Git from PowerShell; Git Bash is `C:/Program Files/Git/bin/bash.exe`, since plain `bash` hits the WindowsApps launcher.

## Checks

- Run the allowed type/import/path checks and the focused regressions. Do not broaden a passing check without a reason; respect test deferrals.
