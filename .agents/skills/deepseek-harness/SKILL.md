---
name: deepseek-harness
description: Use when a DeepSeek Harness tool call is denied, a Windows path fails to write or delete, a piped child process errors, or a shell edit corrupts a file. Covers permission presets, Low-integrity labels, 0700 temp directories and safe edit patterns.
---

# DeepSeek Harness on Windows

Load the full note before diagnosing: [DEEPSEEK-HARNESS.md](../../DEEPSEEK-HARNESS.md).

## Decision order

1. Is the denial a **path ACL** or a **permission preset**? A folder that writes fine elsewhere but not here usually has a `Mandatory Label\Low`, not an ACL deny. Check with `icacls <path>`; repair with [fix-low-integrity.ps1](../../fix-low-integrity.ps1).
2. Is it a **piped child process**? Confined runs deny the pipe `platform.win32_ver` and numpy imports use, so the model-free suite drops from full count to a lower number without any real failure.
3. Is it a **temp directory**? `tempfile.mkdtemp` creates mode 0700, whose DACL excludes a restricted token. Use `CasePaths.temporary_directory` instead.
4. Is it the **tool call itself**? No multi-line Python through `pwsh -Command` and no `@(@('a','b'))` pair arrays; run a scratch script or use the file-edit tool.

## Reporting

- Escalate exactly one operation, then report the outcome; approval never changes the session preset.
- State the execution context before native or GPU work.
