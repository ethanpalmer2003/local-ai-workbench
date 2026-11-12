# Parakeet.cpp

- Windows CPU/Vulkan release installs: `frameworks/asr/parakeetcpp/{cpu,vulkan}/`.
- Initial download: official v0.6.1, advertised SHA256 verified. [Releases](https://github.com/mudler/parakeet.cpp/releases).
- Models: the Parakeet and Silero VAD entries in the catalog, under `models/asr/parakeetcpp/`. [Source](https://huggingface.co/mudler/parakeet-cpp-gguf).
- Profiles: default `110m` is English-only; `v3` is multilingual 0.6B Q8; `nemotron` is Nemotron 3.5 Q8. All weights are downloaded. CPU/Vulkan share model files; offline Silero segmentation is enabled.

```powershell
C:/AI/bat/update_frameworks.bat --only asr/parakeetcpp
C:/AI/bat/models/download_models.bat --group asr --download
C:/AI/.venv/Scripts/python.exe -m scripts.launchers.asr.parakeetcpp.transcribe --input C:/AI/data/input/speech.wav
C:/AI/.venv/Scripts/python.exe -m scripts.launchers.asr.parakeetcpp.transcribe --profile v3 --input C:/AI/data/input/speech.wav
C:/AI/.venv/Scripts/python.exe -m scripts.launchers.asr.parakeetcpp.transcribe --profile nemotron --build cpu --stream --language en --input C:/AI/data/input/speech.wav
```

- CPU -> `--build cpu`; default Vulkan -> `Vulkan0`. Settings: `PARAKEETCPP_ASR`, four threads.
- `--timestamps`, `--json`, `--no-vad`, `--model PATH`, `--vad-model PATH` provide explicit overrides.
- Updater tracks official stable assets without executing version checks. All three models have resident comparison adapters. v3 and CPU Nemotron practice gateways are available.
- v0.6.1 CPU/Vulkan transcription, optional Silero segmentation and VAD-only checks pass on saved English speech. [Evidence](../../../notes/NATIVE-VALIDATION.md); upstream's older master-only VAD note is stale.
- [Nemotron CPU streaming practice](NEMOTRON-STREAMING.md) uses a separate pinned C API build. AudioCpp Nemotron remains default.
- Installed Vulkan Nemotron streaming crashes with an access violation; CPU streaming passes. The shared file profile explicitly selects CPU for streaming, Vulkan for offline. Streaming disables offline VAD; `--json` is incompatible with `--stream`. The CPU C API adapter additionally supports paced PCM with shared Silero turns.
- Later: multilingual/noisy accuracy, streaming latency and shared GPU resource comparisons.
- Upstream speed clips are demonstrations, not local performance results. [Deferred work](../../../notes/asr/ASR-IMPLEMENTATION.md).
