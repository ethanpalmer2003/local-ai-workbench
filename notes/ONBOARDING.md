# New-machine setup

- Workspace root: the checkout root (`AI_ROOT` below); interpreter/environment: `.venv`, managed with uv. Dependencies: declared in [pyproject.toml](../pyproject.toml), resolved in `uv.lock`; [sync_python_env.bat](../bat/models/sync_python_env.bat) runs `uv sync --frozen --group dev` against that venv. Package installs require approval.
- CPU torch/torchaudio use the PyTorch CPU index. Native framework packages and model downloads are separate from Python dependencies.
- Secrets: `scripts/.env`; HF home: `data/huggingface`. Never copy credentials into source/docs.
- Canonical component/native-layout map: [project_config.py](../scripts/config/project_config.py); [configuration ownership](../scripts/config/README.md).

```powershell
bat/update_frameworks.bat --check-only
bat/models/download_models.bat --active --list
bat/models/check_installed_models.bat
```

- Review the plan before updates/downloads. `in_use` controls restore coverage, not launcher model choice; disabled/manual entries remain separate.
- Framework updater covers its catalog only. Native desktop apps, optional services, custom ComfyUI nodes and personal settings may require manual installation.
- ASR: current Whisper Vulkan needs Visual Studio C++ Build Tools/CMake/Ninja/Vulkan SDK for explicit rebuild; Parakeet has CPU/Vulkan prebuilts; Handy has a portable installer.
- External Kokoro needs the separate eSpeak DLL/data under `audiocpp/additions/espeak-ng`; native model formats differ between AudioCpp and Kobold.
- ComfyUI uses mapped typed model folders and the config/workflow sync kept here. Strata keeps native registered paths and model/pack layout.
- Personal inputs live in the untracked overlay `data/input/` ([layout](../scripts/config/notes/INPUTS.md)): clips, transcripts, character cards and extra model entries. Downloads do not restore them, and custom voice variants cannot be recreated.
- Client sessions/native state remain separate from installs; preserve existing native preferences and required junctions/hard links.
- Verify structure/import/types first; actual GPU/model/UI checks require explicit scope and execution-context/session safety. [Entry guide](../scripts/README.md), [tests](../scripts/tests/README.md), [remaining blockers](TODO.md).
