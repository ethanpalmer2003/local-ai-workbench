# Code

- Direct flow; a helper carries reused behavior, a class carries state or policy.
- A file opens with its constants and helpers in order of use, and ends with its entry function and the `__main__` guard.
- One wait, one probe, one timer: [wait.py](../scripts/shared/wait.py) owns `wait_ready` and `http_ready`, [timing.py](../scripts/shared/timing.py) owns `timed`; a different question gets its own name.
- A name is explained once, in its owner's docstring; an import says why this module needs it, never what it does.
- Functions stay at McCabe complexity 10 or below; extract by responsibility, and keep unexpected tracebacks.
- Abnormal state is raised and caught, not flattened into a value: a missing upstream is `NoUpstreamError`, so an empty list means a clean tree; a sentinel stays only where the caller reads it as no evidence.
- A Python file stays under `MAX_FILE_LINES` (800, `inventory_code`), warns from `WARN_FILE_LINES` (600), and longer ones are listed in `lists/file-length-baseline.json`; signatures stay under the annotation cap.
- Keep lifecycle (`Startup`, `Request`, `StartupRequest`) and scope (`Generic`, `Shared`) explicit in settings.
- Preserve external keys, flags and IDs; fix a contract where it is defined.
- Suppressions live in `pyproject.toml` with a reason; an inline `# noqa` is rejected, so restructure and narrow the glob.
- HTTP: `requests` is the client, probes included; `httpx` for HTTP/2 or an async fan-out; `urllib.request` is legacy and shrinks as files are touched. One way per job: static imports, with `dynamic_imports.py` refusing an unlisted loader; uv and `uv.lock` are the only package manager and resolution.
- Shared path/model/proxy defaults live in configuration; orchestration switches stay local.
- Signatures and calls stay single-line up to 120 characters, pass-through arguments last.
- No line exceeds 120 characters: `checks/line_length.py` accepts template and token-like strings and flags prose and code. `python -m scripts.review.limits` prints every numeric rule with its limit and exceptions.
- Trash is grouped by day (`trash/YYYY-MM-DD`, `config/trash.py`); empty directories are deleted.
- ASCII punctuation only: `scripts/review/checks/typography.py` rejects dashes, curly quotes, ellipsis, no-break spaces and a spaced dash in prose.
- Pick defaults from measured evidence; keep the caveats with them.
- Use what the framework or model already reports instead of a copy; a tracked page keeps only what must render with no weight installed, and a check compares it to the packaged spec.

## Imports and paths

- Import heavy or optional dependencies where they are used; keep python-dotenv optional.
- Dependencies stay as new as every dependent allows: read `dist-info`, re-lock with uv, delete pins nothing imports.
- Import `project_cfg` from `config/project_config.py` and backend settings as `cfg` from `launchers/launcher_config.py`, module-qualified.
- Derive paths from canonical roots, create directories explicitly, and write generated image bytes to the target file.

## Execution

- Run modules as `scripts.*` from `C:/AI`; wrappers set the working directory.
- PowerShell uses absolute forward-slash paths and a working directory.
- Run Git from PowerShell; Git Bash is `C:/Program Files/Git/bin/bash.exe`, since plain `bash` hits WindowsApps.

## Checks

- Run the allowed type/import/path checks and the focused regressions; do not broaden a passing check without a reason, and respect test deferrals.
