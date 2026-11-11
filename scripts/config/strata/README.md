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

- Current install (0.2.13): the app keeps its own tree under `%LOCALAPPDATA%\Strata\` (`components`, `install`, `logs`, `procs`, `runtime`, `tuning`) and its WebView profile under `%LOCALAPPDATA%\ai.strata.desktop\EBWebView`. Agent settings live in `%USERPROFILE%\.strata`.
- Workspace state: `scripts/state/strata/` holds the engine and console logs the profiles point at; its `desktop/` copy is from before the reinstall and is not read by the current app.
- The relocation junctions and `relocation.json` from the earlier workspace relocation are no longer present: reinstalling 0.2.13 recreated real folders in the profile. Re-establishing them is not planned; treat the profile paths as authoritative.
- Model weights stay under `C:/AI/data/`; binaries under `C:/AI/frameworks/`; app-updated engine components are the ones inside the profile tree.
- Historical relocation verification (../../tests/output/regression/strata_relocation/unreviewed/1792964068994666100/artifacts/verification.json) describes the pre-reinstall layout only.
