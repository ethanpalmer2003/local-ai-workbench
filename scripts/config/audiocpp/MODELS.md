# Audio models

Both are downloaded under `C:/AI/data/huggingface/models/audiocpp/`. AudioCpp v0.9.3 Vulkan and official ROCm register both families.

Ids, download sizes and output modes are owned by the [model catalog](../models/catalog.json); `server.json` loads the same entries. In short: a small TTS/cloning checkpoint with streaming and instruction control, and a much heavier audio understanding/generation checkpoint that also covers ASR and speech-to-speech.

The heavier checkpoint quantizes mainly its Thinker experts; that does not proportionally shrink TTS-only runtime memory.

## Test page

- Start `bat/browser/launch_test.bat`; choose either model from the TTS model selector.
- Existing character voices use reference cloning; playback is 44100 Hz.
- The TTS checkpoint supports Streaming PCM and Complete WAV; Instruction sends native `instruct`.
- The heavier checkpoint defaults to Complete WAV. Streaming and unsupported voice-instruction controls are disabled; explicit streaming requests are rejected before inference.
- The launcher default is unchanged. Models load lazily; selecting a dropdown does not synthesize speech.

## Brief checks

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case ming3-tts
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case ming3-audio --loaders-only
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.tests.cases.audiocpp.audiocpp_backend_compare --case ming3-audio --backend vulkan
```

- Omit `--backend` to check both official builds sequentially. Default: one short warmup and one measured request, English named voice `US_James`. TTS seed 1895; heavier-model seed 42. `--text`, `--samples`, `--timeout` are available.
- Generated smoke configs contain only the selected model. Existing services on test ports are preserved/refused.
- The TTS checkpoint passed synthesis on Vulkan/ROCm; page cloning/SSE/browser playback also passed. The heavier checkpoint's loader registration and live native/proxy catalog are verified; its synthesis has not run. [Evidence](../../../notes/NATIVE-VALIDATION.md).
- A single sentence is a compatibility screen, not a quality/ranking benchmark. ASR/speech-to-speech are available natively but are not wired into this TTS page.

Editable native model and session options: [server.json](server.json). Sources/options: [TTS model guide](https://github.com/0xShug0/audio.cpp/blob/v0.9.3/docs/models/ming3_tts.md), [heavier model guide](https://github.com/0xShug0/audio.cpp/blob/v0.9.3/docs/models/ming3_audio.md). Pinned download identities stay in [model catalog](../models/catalog.json); bulk restore remains opt-in.
