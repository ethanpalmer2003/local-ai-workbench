# Additional ASR engines

All required weights are downloaded and pinned in [the model catalog](../../config/models/catalog.json). Shared settings: [file_profiles.py](../../config/asr/file_profiles.py). No servers start automatically; the configured engine is read from `ASR_SERVICE`.

| `--engine` | Weights (catalog owns identity) | Configured modes |
| --- | --- | --- |
| `nemo-speechcpp` | Q8_0 GGUF | Offline, stateful streaming WAV, live microphone |
| `speechcpp` | Packed Q8_0 ASR + Silero VAD | Offline, VAD-delimited live microphone |
| `audiocpp-vulkan`, `audiocpp-rocm` | Q8_0 GGUF | Offline, stateful streaming WAV |
| `audiocpp-ming-audio-tiny` | Existing Q4_K audio GGUF | Offline ASR; expert offload; auto language |
| `parakeetcpp-v3` | TDT encoder, Q8 | Vulkan offline, Silero VAD |
| `parakeetcpp-nemotron-streaming` | Streaming encoder, Q8 | Vulkan offline/VAD; CPU streaming WAV |

NeMo and AudioCpp require separate GGUF conversions. speech.cpp uses its packed ASR file, not llama.cpp's main/projector pair. The default backend is Vulkan, except the explicit AudioCpp ROCm profile.

```powershell
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.launchers.asr.shared.file_cli --list
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.launchers.asr.shared.file_cli --engine nemo-speechcpp --input C:/AI/data/input/speech.wav --mode streaming
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.launchers.asr.shared.file_cli --engine speechcpp --input C:/AI/data/input/speech.wav
C:/AI/scripts/.venv/Scripts/python.exe -m scripts.launchers.asr.shared.file_cli --engine audiocpp-vulkan --input C:/AI/data/input/speech.wav --mode streaming
```

Use mono 16 kHz PCM16 WAV for common file comparisons. The Python entry also accepts `--engine audiocpp-rocm`. `--print-command` previews arguments without loading weights. `--output transcript.txt` is available for NeMo and AudioCpp; other CLIs write text to stdout. Existing output files are refused.

`--mode live` explicitly activates microphone capture for NeMo or speech.cpp. speech.cpp's VAD-driven utterance recognition differs from Nemotron's stateful streaming. Sherpa's ASR profile was retired on 2026-11-08; the Sherpa framework stays installed for TTS.

Model restore: `download_models.bat --active --group asr --download`; AudioCpp uses model ID `audiocpp/nemotron-3.5-q8_0`. Native auto-fetch caches stay inside canonical model roots. [Downloads/evidence](../../../notes/asr/ASR-DOWNLOADS.md), [comparison](../../tests/cases/asr/COMPARISON.md).

Every configured profile passes brief file checks. [Additional profiles and limits](../../tests/notes/asr/ASR-EXTRA-PROFILES.md) cover the additional profiles. Resident adapters are available; microphone/first-partial latency and server/browser integration remain unverified. Nemotron streaming explicitly uses CPU because the installed Vulkan path crashes.
