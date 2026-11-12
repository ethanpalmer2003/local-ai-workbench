# Configuration ownership

| Setting | Owner |
| --- | --- |
| Roots, component keys, native-layout overrides | [project_config.py](project_config.py) |
| Model identity, source, destination, restore selection | [models/](models/__init__.py) |
| Active service/client/model defaults | [launcher_config.py](../launchers/launcher_config.py) |
| llama.cpp profiles / native INI | [profiles](../launchers/llamacpp/llamacpp_profiles.py), [llamacpp/](llamacpp/) |
| Pi packages/extensions/environment | [coding_agents/pi/](coding_agents/pi/README.md) |
| AudioCpp native model/session options | [audiocpp/server.json](audiocpp/server.json) |
| Framework update coverage | [framework_catalog.py](../download/frameworks/framework_catalog.py) |
| ComfyUI paths/workflows/node | [comfyui/](comfyui/README.md) |
| Device tuning decisions | `TUNING.md` per component: [comfyui](comfyui/TUNING.md), [sdcpp](sdcpp/TUNING.md), [llamacpp](llamacpp/TUNING.md), [strata](strata/TUNING.md) |

- One editable owner per setting. Native config is read directly when supported; Python selects catalog IDs and runtime overrides.
- Paths use `project_cfg.component(key)`; `_DIR` values are `Path`, converted at CLI/JSON boundaries. Component prefix first; service/client bindings use `_SERVICE`/`_CLIENT`.
- Source edits require restarting affected consumers; preserve existing sessions until authorized to restart.

```powershell
python -m scripts.config.sync_configs
python -m scripts.config.sync_configs --only comfyui --apply
```

- Preview is read-only. Apply manages owned ComfyUI copies, preserving replaced files in trash; it does not install packages or restart servers.
- Pi package/extension synchronization is separate and may install/remove packages.
- Personal inputs are not in the repo: [local inputs](notes/INPUTS.md). Every default's owner and override: [defaults map](notes/DEFAULTS.md).
- [Generated files](notes/GENERATED-FILES.md) records startup derivations and required native copies.
- Historical configs/results are evidence, never editable defaults. Credentials stay out of Git/reports.
- Layout/docs guards, the full review and their commands: [checks](../../.agents/CHECKS.md).

- Model registry: edit [models/catalog.json](models/catalog.json); import the package API. `models/ids.py` is generated; category modules are compatibility wrappers. Storage group, task roles and runtime candidates are separate. Runtime candidates do not prove tested compatibility.
- Inspect, add or retire a model: `python -m scripts.tools.model_admin where|add|remove|replace ...`; `--apply` edits `catalog.json`, regenerates `ids.py`, rewrites active references and moves weights to trash. Strata native configs remain a manual boundary.

## Notes

- [Images on demand](notes/IMAGE-ON-DEMAND.md)
- [Language practice](notes/LANGUAGE-PRACTICE.md)
- [Speech model languages](notes/MODEL-LANGUAGES.md)
- [Shared GPU policy](notes/SHARED-GPU.md)

## Workflow defaults

- Each workflow's default speech stack is one named profile in [launcher_config.py](../launchers/launcher_config.py): `KOBOLD_CHAT` (KoboldCpp; Rocinante chat, Breeze TTS using the overlay voice when one is configured, no external ASR) and `LANGUAGE_PRACTICE` (Gemma chat, Kokoro TTS without cloning, AudioCpp ASR). Service settings and the `chat_models`/`practice_models` defaults read these profiles; do not inline the values or derive one default from another.
- Model ids live in separate namespaces: registry catalog labels (`models.MODELS[].label`, the canonical download/selection id), AudioCpp native ids (`audiocpp/server.json`, the request `model`), and KoboldCpp keys (`KOBOLDCPP_MODELS`). A profile field holds the id its workflow's layer uses; `framework` names the namespace. Prefer one shared canonical id where the same model appears on several surfaces.
- Delivery default for every surface is streaming then chunked then whole, each surface passing only the modes its framework supports, with per-model overrides in `state/shared/speech_delivery.json`.
- Local service credentials live in `scripts/.env`; the KoboldCpp admin password reaches the launcher from there as `--adminpassword`, and the tracked config keeps the field empty.
