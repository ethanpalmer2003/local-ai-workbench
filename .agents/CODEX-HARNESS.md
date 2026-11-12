# Codex on Windows

- Git Bash has failed to start in the current sandbox with an MSYS access-denied error. Use PowerShell for equivalent authorized work.
- Separate shell startup errors from command and approval denials. When a command is denied, stop and report it through the approval workflow. The denial remains in force across shells and wrappers.
- The saved legacy sandbox setting does not elevate the current session. Permission profiles and command allow-lists remain controlled by Codex.

## Loopback and native checks

- Default `functions.exec_command` is sandboxed. On this host it can report `AppContainer=true` and deny sockets to `127.0.0.1`, even when the user's browser can reach the service. A sandbox socket error is inconclusive; do not report the service as down from that result.
- Check the current invocation with `python -m scripts.launchers.runtime.execution_context`. The old `scripts.launchers.execution_context` module path is absent.
- Before local health checks, process discovery or native workloads, state whether that invocation is sandboxed, approved outside the sandbox or unknown. If AppContainer blocks a needed read-only check, request a scoped `require_escalated` retry and check its token again; approval does not carry over to later commands.
