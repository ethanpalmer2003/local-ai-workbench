# Handy desktop dictation

- Portable Windows app v0.9.8 installed at `frameworks/asr/handy/app/`; [upstream](https://github.com/cjpais/Handy).
- Hotkey -> microphone/VAD -> local transcription -> paste into another app. Bundles inference; Windows x64 supports Vulkan through transcribe-cpp and ONNX models through transcribe-rs.
- Uses its own libraries, not the standalone ASR executables. Model compatibility depends on its bundled engine; ONNX and GGUF packages differ.

```powershell
python -m scripts.launchers.asr.handy.app
C:/AI/bat/update_frameworks.bat --only asr/handy
```

- First use -> select custom `ggml-large-v3-turbo-q5_0`, configure microphone and recording shortcut.
- Existing Whisper weights are hard-linked from `models/asr/whispercpp/` into `app/Data/models/`; no duplicate allocation. Keep the Q5 filename; Handy's stock Turbo entry refers to another package.
- Portable settings/history/models/recordings stay in `app/Data/`. Its VAD is separate from the Parakeet GGUF VAD package.
- Framework updater downloads/verifies the installer into `installer/` and, on apply, installs the portable app when `app/` is missing; an installed app updates through Handy itself.
- Fresh setup -> `bat/update_frameworks.bat --only asr/handy`; preserves existing app/data and prepares the model link when the source exists.
- Owned paths resolve through `project_cfg.component("asr/handy")`; native portable layout stays intact.
- Dictation is local after model setup; optional post-processing providers have separate network behavior.
- UI inspected 2026-10-31: v0.9.8 opened to first-use model selection; the existing custom GGML Large V3 Turbo Q5 0 model was selected. General settings show the default microphone, average-all-channels input, Ctrl+Space to transcribe and Escape to cancel. No recording/transcription or paste was tested; device and dictation checks remain open.
