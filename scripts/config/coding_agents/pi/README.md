# Pi configuration

- Package/extension owner: [inventory.py](inventory.py); manifest/path resolver: [packages.py](packages.py). Launcher settings: `PI_CLIENT`.
- Install: `frameworks/coding_agents/pi`; editable sources: `config/coding_agents/pi`; state: `state/coding_agents/pi/agent`.
- `PI_CODING_AGENT_DIR` selects the active home. Native package names, provider IDs and environment names keep their required spelling.
- Enabled extensions/default tools/CLI flags/environment come from one inventory; do not maintain another package list in a launcher.
- Lens native settings: [lens.json](lens.json); extension code: [extensions/](extensions/). Generated native copies belong in the selected agent home.

```powershell
C:/AI/bat/update_frameworks.bat --only coding_agents/pi --check-only
C:/AI/bat/update_frameworks.bat --only coding_agents/pi
```

- Check/preview before applying; package synchronization can install/remove dependencies and needs approval. Preserve personal settings/sessions and credentials.
- Write containment and permission hooks are owned here; [security limits](../../../../.agents/AGENT-SECURITY.md). They do not replace OS permissions or make Bash a full sandbox.
- Benchmarks use the same extension/tool mode across clients; explicit differences must be recorded. [Shared comparison guide](../../../benchmarks/coding_agents/README.md).
