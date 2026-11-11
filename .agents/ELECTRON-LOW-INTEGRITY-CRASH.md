# Electron apps crashing from a Low integrity label

DSH-adjacent Electron apps (DeepSeek Harness, VS Code forks, any Electron shell) can exit immediately with `-2147483645` (`0x80000003`) when their install folder carries a **Low** mandatory integrity label.

- Cause: a process at Medium integrity may not write to a Low-labelled object, and Electron's own process launch inherits the label, so the app aborts at startup. The DACL looks permissive while the label still refuses the write.
- Confirm: `icacls <path>` shows a `Mandatory Label\Low Mandatory Level` line. A healthy install shows `Medium`.
- Repair: [fix_low_integrity.ps1](../scripts/tools/fix_low_integrity.ps1) scans for the label and runs `icacls <path> /setintegritylevel M`, recursing with `(OI)(CI)M` for folders. `-Mode Check` only reports.

```powershell
scripts\tools\fix_low_integrity.ps1 -Paths C:\AI\frameworks
scripts\tools\fix_low_integrity.ps1 -Paths C:\AI -Mode Fix
```

Agent consequences:

- The same label shows up as `[sandbox: file access denied]`-style failures or raw `Access is denied` on files whose DACL grants full control. Treat a permissive DACL plus a denied write as a label problem, not a permission-profile problem.
- It affects moves and deletions, not only writes, so "move it to trash" fails with the same error.
- Repair the label, then repeat the failed operation once; do not widen sandbox or approval settings to work around it.
- A Low label on the workspace root (`C:\AI`) propagates to everything created beneath it and is the usual cause: apps write nothing, WebView2 and child-process launches fail with access denied or `0x800700AA`. Restore the root first, then the subtrees the app uses; setting a subtree to Low to satisfy one sandboxed child breaks every normal app.
