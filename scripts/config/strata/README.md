# Strata backend configuration

- Pi/backend source: [decode.json](decode.json) (default) and [prefill.json](prefill.json); editable native JSON, never regenerated.
- Which profile to run, what each was measured at and what stays unmeasured: [TUNING.md](TUNING.md).
- Switching: `--config C:/AI/scripts/config/strata/prefill.json` on the launch bat, or edit `STRATA.config_path`. A loaded model keeps its settings until restart.
- Default location: `STRATA.config_path` in [launcher_config.py](../../launchers/launcher_config.py).
- Alternate file: `C:/AI/bat/launch_strata_pi_agent.bat --config C:/path/to/config.json`.
- Launch host/port/API key: supplied separately by the launcher; API key kept in memory.
- Model paths/load/memory settings: edit `decode.json`; restart the backend.
- Engine/console logs: `scripts/state/strata/`.
- Shared source: desktop and Pi use this same file; no config synchronization or regeneration.
- Desktop folder preference: app-managed under the profile tree above; the state copy is historical.
- Desktop re-reads this folder on launch; an open desktop must restart.
- Desktop discovery copies it as `strata-<model-id>.json`; these sources keep role names.
- Original desktop profile and prior preference: preserved in `C:/AI/trash/`.
- Shared edits: apply when each backend next starts; an already-loaded model keeps its current settings.
- Backend-only Pi launch: rejects nonempty inherited MCP servers.

## App-managed data

The app's profile tree is relocated into this workspace with NTFS directory junctions, so one copy exists:

| Profile path | Real folder under `C:/AI/scripts/state/strata/` |
| --- | --- |
| `%LOCALAPPDATA%/Strata` | `desktop/` (components, runtime, logs, tuning, install) |
| `%LOCALAPPDATA%/ai.strata.desktop` | `webview/` (WebView2 profile) |

- Agent settings stay in `%USERPROFILE%/.strata`; sessions and host preferences in `home/`; terminal profiles in `terminal/`.
- Record: `relocation.json` in this folder, written when the junctions were recreated after the 0.2.13 reinstall replaced the originals.
- Keep the junctions and their targets; an installer may replace a junction, so recheck after a major update and repeat the move plus `mklink /J` if the app wrote a real folder again.
- Model weights stay under `C:/AI/data/`; binaries under `C:/AI/frameworks/`; the app updates its engine components inside the relocated `desktop/`.
- An older workspace copy made before the reinstall is retired to trash; the table above is the only live mapping.
