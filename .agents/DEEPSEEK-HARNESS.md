# DeepSeek Harness on Windows

- Permission is two knobs only: sandbox mode and approval policy, bundled into presets. There is no command allow-list and no "allow always" grant; an approval covers one operation. Switch with `/permission`, set a durable default in Settings → Permissions, or `defaultPreset` in `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml` under `@deepseek-ai/dsh-permission-presets`.
- A denial that looks like a permanent folder ACL is usually a Low mandatory integrity label, which blocks writes and deletes even at full access. Check the object with `icacls <path>`: a `Mandatory Label\Low` line is the cause. Repair with [fix_low_integrity.ps1](../scripts/tools/fix_low_integrity.ps1); background in [ELECTRON-LOW-INTEGRITY-CRASH.md](ELECTRON-LOW-INTEGRITY-CRASH.md).
- `tempfile.mkdtemp` and `TemporaryDirectory` create mode 0700. On Windows that DACL excludes a restricted sandbox token, so a confined run cannot create or delete inside the directory it just made. Create scratch directories with `Path.mkdir()`: `CasePaths.temporary_directory`, the pi write-probe and the framework staging directories do.
- The model-free suite passes at full access; under `workspace-write` some tests fail, because the sandbox denies the piped child process that `platform.win32_ver` and scipy's numpy import use.
- Withdraw a launcher by moving it into `C:/AI/trash`; `bat/` blocks that only while its integrity label is wrong.
- Files written by an earlier low-integrity run can stay unreadable (`.pytest_cache`, `tmp*` run directories, which then break the structure review). Repair the label, then remove them.
- No multi-line Python through `pwsh -Command`: heredocs and quoting break, and a broken edit corrupts files silently. Run a scratch script from `scripts/state/`, or use the file-edit tool.
- PowerShell flattens `@(@('a','b'))` to two strings, so the loop indexes characters. Use Python for pair lists.
- A denial is a policy decision, not a retry prompt: escalate that exact operation once, then report the outcome.
- Repo search layers, now all installed: the `dsh-graphify` plugin (cloned from
  `QuantumKuba/dsh-graphify-plugin`, dependencies installed with `npm install --omit=dev`, tarball or link
  installs alone leave it unable to import `@deepseek-ai/schemastery`) serves the Graphify code graph built by
  `graphifyy 0.9.57`; `graphify-out/` is ignored, and a code-only graph comes from `graphify update <repo>
  --no-cluster` plus `cluster-only --no-label`, which needs no model. The earlier `dsh-graphify` npm 404 was a
  wrong repository name, not a withdrawn package.
- The desktop profile caps a foreground `pwsh` command at 60 s and clamps a longer per-call request, so no single command can stall a turn for longer. A command that reaches the deadline is promoted to a background job: stop it with `job_kill` without reading its output, because a search that already timed out has nothing worth collecting.
- The built-in `web_search` bills a DeepSeek account and answers `402 Insufficient Balance` when that account is empty, whatever model route the conversation uses; an OpenCode subscription cannot pay for it, and neither can `OPENCODE_ENABLE_EXA` or `opencode.json`, which configure the OpenCode CLI rather than this harness. Searching goes through the Exa MCP instead: the profile bundle `%USERPROFILE%/.dsh/bundles/exa-mcp` mounts `https://mcp.exa.ai/mcp` and exposes `mcp__exa__web_search_exa` and `mcp__exa__web_fetch_exa` with no credential. When those tools are absent, `web_fetch` still reaches a Bing query with `format=rss` or the GitHub search API, while DuckDuckGo and Mojeek return captchas; say a general search is unavailable rather than guessing.
