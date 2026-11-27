# Launcher script guard

Why: a scratch script that reached for `launch_module` started services the launcher did not own, so a
restart left two stacks on one machine and the extras had to be killed by hand. The launcher already owns
port clearing, supervision and teardown; hand-rolling that is how duplicates happen.

What it refuses, per tool call:

- Writing or editing a `.py` file outside the repository whose text mentions `launch_util`,
  `launch_module` or `scripts.launchers`.
- Running such a file through `pwsh`/`bash` when it already exists outside the repository.

What it allows: anything inside the repository, where launcher modules and their tests belong.

The refusal names the supported path: start a stack with `python -m scripts.launchers.<stack>`, read
readiness from its ports, the health endpoint and `/v1/models`, and stop it with
`python -m scripts.launchers.kill_all_services` or by closing the launcher window.

Limits: the guard reads the content being written, not intent. A script created by other means (an
installer, a copied file) is caught only when run through a shell call this guard sees, and shell
obfuscation such as a base64 payload is out of scope. The rule it enforces is stated in
[the failure modes](../../../.agents/FAILURES.md) and [the launcher page](../../../scripts/launchers/PROXIES.md).
