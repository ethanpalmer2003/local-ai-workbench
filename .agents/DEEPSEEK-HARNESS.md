# DeepSeek Harness on Windows

- Permission is two knobs only: sandbox mode and approval policy, bundled into presets. There is no command allow-list and no "allow always" grant; an approval covers one operation. Switch with `/permission`, set a durable default in Settings → Permissions, or `defaultPreset` in `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml` under `@deepseek-ai/dsh-permission-presets`.
- A denial that looks like a permanent folder ACL is usually a Low mandatory integrity label, which blocks writes and deletes even at full access. Check the object with `icacls <path>`: a `Mandatory Label\Low` line is the cause. Repair with [fix_low_integrity.ps1](../scripts/tools/fix_low_integrity.ps1); background in [ELECTRON-LOW-INTEGRITY-CRASH.md](ELECTRON-LOW-INTEGRITY-CRASH.md).
- `tempfile.mkdtemp` and `TemporaryDirectory` create mode 0700. On Windows that DACL excludes a restricted sandbox token, so a confined run cannot create or delete inside the directory it just made. Create scratch directories with `Path.mkdir()`: `CasePaths.temporary_directory`, the pi write-probe and the framework staging directories do.
- The model-free suite is 441/441 at full access. Under `workspace-write` it drops to 432/441, because the sandbox denies the piped child process that `platform.win32_ver` and scipy's numpy import use.
- Withdraw a launcher by moving it into `C:/AI/trash`; `bat/` blocks that only while its integrity label is wrong.
- Files written by an earlier low-integrity run can stay unreadable (`.pytest_cache`, `tmp*` run directories, which then break the structure review). Repair the label, then remove them.
- No multi-line Python through `pwsh -Command`: heredocs and quoting break, and a broken edit corrupts files silently. Run a scratch script from `scripts/state/`, or use the file-edit tool.
- PowerShell flattens `@(@('a','b'))` to two strings, so the loop indexes characters. Use Python for pair lists.
- A denial is a policy decision, not a retry prompt: escalate that exact operation once, then report the outcome.
