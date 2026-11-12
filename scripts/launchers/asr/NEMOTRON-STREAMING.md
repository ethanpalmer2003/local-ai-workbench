# Nemotron streaming practice

AudioCpp Vulkan remains default. Two alternatives use the same shared Silero
controller: threshold 0.5, 700 ms silence, 300 ms pre-roll and 16 kHz mono PCM16.
All pair with Gemma E4B in llama.cpp or Kobold and Vulkan Kokoro. Each runtime
uses its compatible Nemotron 3.5 Q8 conversion; GGUF files are not interchangeable
by assumption. No streaming option silently falls back to offline decoding.

| Engine option | Settings | Transport |
| --- | --- | --- |
| `audiocpp-nemotron` | `AUDIOCPP_VAD`, port 8894 | Chunked PCM/SSE; one ASR/Kokoro server |
| `nemo-nemotron` | `NEMO_SPEECHCPP_ASR`, port 8899 | Realtime WebSocket; separate Kokoro server |
| `parakeetcpp-nemotron-cpu` | `PARAKEETCPP_STREAM_ASR`, port 8900 | CPU C API behind owned chunked PCM/SSE server; separate Kokoro |

Launch a language-practice browser launcher (`bat/browser/launch_language.bat`
or `bat/browser/launch_language_kobold.bat`) with `--transcription-engine`
(`nemo-nemotron` or `parakeetcpp-nemotron-cpu`). Press **Start listening**.

NeMo uses an owned Node helper with built-in WebSocket support; no npm packages.
The helper starts with microphone setup, before turn timing. Native endpointing
is set to 10 seconds; the shared Silero event sends the actual commit. Model
sessions are independent per turn and capped at two. Stop/idle/shutdown clean up.

## Parakeet CPU library

Official v0.6.1 Windows archives include CLI/server executables but no streaming
DLL. The optional CPU library is built separately under
`frameworks/asr/parakeetcpp/cpu-stream/`; official `cpu/` and `vulkan/` stay intact.
It uses the pinned v0.6.1 commit/submodule, CPU-only ggml and eight native default
compute threads. One active native stream is allowed; overlap returns 429.

Reproduce with installed Visual Studio/CMake/Ninja:

```powershell
C:/AI/.venv/Scripts/python.exe -m scripts.download.frameworks.asr.parakeetcpp
```

The build records its source commit, options, logs and execution context in
`.build_manifest.json`. It needs native execution approval, not package changes.
The updater lists it as optional/manual, excluded from routine rebuilds.
Vulkan Nemotron streaming remains disabled after the recorded access violation;
no newer stable release fixing it was found. Retry after a relevant fix.

[Brief comparison and limits](../../tests/notes/asr/NEMOTRON-STREAMING.md).
Physical microphone/acoustic echo, multilingual accuracy and interruption remain
unverified. Practice pauses recognition during tutor generation/playback.
