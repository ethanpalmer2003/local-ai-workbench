# llama.cpp UI patches

Indexed with the other upstream responses: [notes/UPSTREAM-INDEX.md](../../../../notes/UPSTREAM-INDEX.md).

The patch set targets `frameworks/llamacpp/rdna/tools/ui`:

- [workspace-speech-additions.patch](workspace-speech-additions.patch) adds the settings panel and type declarations.
- [speech_ui.patch](speech_ui.patch) connects the existing UI components to workspace speech.

From the llama.cpp checkout, apply the additions patch first and `speech_ui.patch` second. Skip either patch if it is already applied.

From that source directory, install dependencies, check and build:

```powershell
npm.cmd ci --ignore-scripts
npm.cmd run check
$env:LLAMA_UI_OUT_DIR = 'C:/AI/frameworks/llamacpp/additions/speech-ui'
npm.cmd run build
```

The gateway serves the output from `frameworks/llamacpp/additions/speech-ui`. Rebuilding does not update backend binaries or models.
