# Pi write containment

- Pi runs with the Windows user's permissions; extensions plus OS permissions enforce access.
- `scripts/config/coding_agents/pi/extensions/protected-paths.ts` restricts write/edit tools to `C:/AI`.
- `permission-gate.ts` prompts for destructive/broad privilege commands and blocks them non-interactively.
- The launcher deploys extensions to the client's canonical `agent_dir/extensions`, discovered through `PI_CODING_AGENT_DIR`; root `.pi` is unused.
- Bash can still write outside the workspace through other commands. A dedicated Windows user with NTFS restrictions provides the OS boundary.
