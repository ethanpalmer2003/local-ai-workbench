# Electron apps crashing from a Low integrity label

DSH-adjacent Electron apps (DeepSeek Harness, VS Code forks, any Electron shell) can exit immediately with `-2147483645` (`0x80000003`) when their install folder carries a **Low** mandatory integrity label.

- Cause: a process at Medium integrity may not write to a Low-labelled object, and Electron's own process launch inherits the label, so the app aborts at startup. The DACL looks permissive while the label still refuses the write.
- Confirm: `icacls <path>` shows a `Mandatory Label\Low Mandatory Level` line. A healthy install shows `Medium`.
- Repair: [fix-low-integrity.ps1](fix-low-integrity.ps1) scans for the label and runs `icacls <path> /setintegritylevel M`, recursing with `(OI)(CI)M` for folders. `-Mode Check` only reports.

```powershell
.\.agents\fix-low-integrity.ps1 -Paths C:\AI\frameworks
.\.agents\fix-low-integrity.ps1 -Paths C:\AI -Mode Fix
```

Agent consequences:

- The same label shows up as `[sandbox: file access denied]`-style failures or raw `Access is denied` on files whose DACL grants full control. Treat a permissive DACL plus a denied write as a label problem, not a permission-profile problem.
- It affects moves and deletions, not only writes, so "move it to trash" fails with the same error.
- Repair the label, then repeat the failed operation once; do not widen sandbox or approval settings to work around it.
