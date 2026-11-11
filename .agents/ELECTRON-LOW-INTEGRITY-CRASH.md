# Low integrity labels breaking apps in the workspace

DSH `workspace-write` stamps an inheritable Low mandatory label on the workspace root and its whole tree, and it stays on disk after the session, a permission change or a restart. Windows uses an image's label to set a process's integrity, so programs started from a Low file run Low and cannot write Medium locations: blank shortcut icons, "publisher could not be verified", Electron crashes (`0x80000003`), WebView2 `0x800700AA`, and `Access is denied` on a permissive DACL.

- Confirm: `icacls <path>` shows `Mandatory Label\Low Mandatory Level:(OI)(CI)(NW)`.
- Repair, after closing every DSH session on that tree: `icacls <dir> /setintegritylevel "(OI)(CI)Medium" /T /C`. `/reset` cannot clear a label.
- Restore the root first; a subtree left Low breaks every normal app. Only when *existing* subdirectories are unwritable while new ones work is the fix the opposite one: `icacls <workspace> /setintegritylevel "(OI)(CI)L" /T`.
- Wrapper: [manage_low_integrity.bat](../bat/manage_low_integrity.bat) checks by default, `--fix` repairs. It covers the root and `frameworks`, `scripts`, `bat`, `.agents`, `notes`, `trash`; models under `data` are skipped because nothing there launches.
- This workspace is a whole workbench with executables and models, so keep DSH on **full access** for `C:\AI`; never use the home directory, a drive root or the DSH install directory as a `workspace-write` workspace.
- When a restricted session has touched `C:\AI`: close it, run the wrapper with `--fix`, then launch the app again. Do not leave a subtree Low to satisfy one sandboxed child; that breaks every normal launch.
- Community write-up: <https://dsh-plugin.org/tutorials/fix-windows-sandbox-low-integrity-label>.
