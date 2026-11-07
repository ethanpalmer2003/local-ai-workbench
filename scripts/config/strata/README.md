# Strata backend configuration

- Pi/backend source: [decode.json](decode.json) (default) and [prefill.json](prefill.json); editable native JSON, never regenerated.
- Two profiles, both measured with the issue #3695 harness (`scripts.benchmarks.inference_engines.benchmark_strata_reference`) on this machine:

| profile | decode | cold prompt read | what it is |
| --- | ---: | ---: | --- |
| [decode.json](decode.json) | 36.9 tok/s | 187 tok/s | experts on the SSD page cache: fastest per generated token |
| [prefill.json](prefill.json) | 24.6 tok/s | 525 tok/s | 18 GiB of experts in RAM plus the reference env switches: fastest to read a fresh prompt |

- Pick by what the workload spends time on: a long fresh prompt (new files, cold session) wants the prefill profile; a long answer or many short turns in a warm session wants the decode profile. Cached prompt tokens cost neither arm, so reuse decides which side dominates.
- Switching: `--config C:/AI/scripts/config/strata/prefill.json` on the launch bat, or edit `STRATA.config_path`. A loaded model keeps its settings until restart.
- Default location: `STRATA.config_path` in [launcher_config.py](../../launchers/launcher_config.py).
- Alternate file: `C:/AI/bat/launch_strata_pi_agent.bat --config C:/path/to/config.json`.
- Experimental RX 7800 XT / 32 GB alternative: [reference profile, tests and limits](REFERENCE.md).
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
- [Verification record](../../tests/output/regression/strata_relocation/unreviewed/1792964068994666100/artifacts/verification.json).
- Desktop UI/model startup: not exercised during relocation.
