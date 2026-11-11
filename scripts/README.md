# Local AI workspace

- Component paths: [project_config.py](config/project_config.py); runtime settings: [launcher_config.py](launchers/launcher_config.py).
- Use one component key wherever files belong to one component; matching keys do not require empty mirror folders. [folder rules](../.agents/FOLDERS.md).
- New machine: [onboarding](../notes/ONBOARDING.md). Pending work: [TODO](../notes/TODO.md); open questions: [OPEN-QUESTIONS](../notes/OPEN-QUESTIONS.md).
- Routine batch entry points: [bat/README.md](../bat/README.md).
- Optional: `bat/tests/refresh_capability_matrix.bat` rewrites the last-run table for the long opt-in checks. It is a reference view, not a required step.
- Two browser pages exist: the shared `/test/` page and the practice page. A manual tool or check becomes a control there, not a new entry point.

| Task | Guide |
| --- | --- |
| Coding with llama.cpp | [guide](launchers/llamacpp/README.md) |
| Strata with Pi | [guide](launchers/strata/README.md) |
| Audio / TTS | [guide](launchers/audiocpp/README.md) |
| Sherpa / Piper | [TTS guide](launchers/audiocpp/RETAINED-TTS.md); official Windows CPU frameworks |
| Koboldcpp + speech/images | [shared GPU](config/notes/SHARED-GPU.md), [swapping](config/notes/IMAGE-ON-DEMAND.md) |
| Ports / proxies | [proxy principle](launchers/PROXIES.md) |
| Language practice / ASR | [ASR guide](launchers/asr/README.md), [comparison setup](tests/cases/asr/COMPARISON.md), [checkpoint](../notes/asr/ASR-IMPLEMENTATION.md) |
| Images | [settings](config/sdcpp/README.md) |
| ComfyUI | [guide](config/comfyui/README.md) |
| Framework updates | [category guide](download/frameworks/UPDATES.md): `llamacpp`, `asr`, `speech`, `other` |
| Model downloads/audit | [guide](download/README.md) |
| Config sync | `python -m scripts.config.sync_configs`, [ownership](config/README.md) |
| Code review | [review guide](review/README.md); [tool inventory](review/TOOLS.md) |
| Tests | [test guide](tests/README.md) |
| Benchmarks | [runners and measurement rules](benchmarks/README.md) |
| Repository tools | [tools](tools/README.md) |
| Shared runtime code | [process, engine, audio/upload and native binding helpers](launchers/shared/README.md) |

## Storage

- `frameworks/<component>/`: third-party installations, grouped under `model_servers/` when the component wraps other engines; `data/huggingface/models/<component>/`: weights.
- `scripts/{config,launchers}/<component>/`: owned configuration/code; see [folder rules](../.agents/FOLDERS.md) for shared and role-wide placement.
- `scripts/tests/{cases,ui}/<component>/`: test sources/assets. New results mirror cases under `tests/output/`; historical output stays in place.
- `scripts/benchmarks/<area>/`: performance runners and shared measurement support. New results go under `benchmarks/output/`; historical test output stays in place.
- `scripts/state/<component>/`: app state; `{logs,cache,generated}/<component>/`: future runtime artifacts.
- `bat/`: routine launchers only (index: [bat/README.md](../bat/README.md)); use the project interpreter from the checkout root.
- Native layouts/shared weights are explicit exceptions in `COMPONENTS`; preserve vendor files, app preferences and evidence.
