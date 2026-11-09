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
- Desktop folder preference: `scripts/state/strata/home/data/native-host.json`, `installDir`.
- Desktop re-reads this folder on launch; an open desktop must restart.
- Desktop discovery copies it as `strata-<model-id>.json`; these sources keep role names.
- Original desktop profile and prior preference: preserved in `C:/AI/trash/`.
- Shared edits: apply when each backend next starts; an already-loaded model keeps its current settings.
- Backend-only Pi launch: rejects nonempty inherited MCP servers.
- Relocation: update both `STRATA.config_path` and the desktop folder preference.

## App-managed data

| Content | Physical location under C:/AI/scripts/state/strata/ |
| --- | --- |
| Sessions, host preferences, uploads | `home/` |
| App settings, managed components, runtime, logs, tuning | `desktop/` |
| Terminal profiles | `terminal/` |
| Desktop WebView directory | `webview/` |
| Relocation record | `relocation.json` |

## Compatibility paths

| Old path | Redirects to under state/strata/ |
| --- | --- |
| `%USERPROFILE%/.strata` | `home/` |
| `%LOCALAPPDATA%/Strata` | `desktop/` |
| `%APPDATA%/Strata` | `terminal/` |
| `%LOCALAPPDATA%/ai.strata.desktop` | `webview/` |

- Old paths: NTFS directory junctions; one physical copy inside `C:/AI`.
- Existing shortcuts and normal settings updates: follow the junctions.
- Keep the junctions and their targets; targets contain the real data.
- Future installers: could replace a junction or introduce another storage path; recheck after major updates.
- Model weights: under `C:/AI/data/`.
- Application binaries: remain under `C:/AI/frameworks/`; app-updated components under `desktop/components/`.
- Verification: junction identity, native profiles/runtime/component paths, shared config pointer and model discovery passed.
- Verification record (../../tests/output/regression/strata_relocation/unreviewed/1792964068994666100/artifacts/verification.json).
- Desktop UI/model startup: not exercised during relocation.
