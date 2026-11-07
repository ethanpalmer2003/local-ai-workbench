# Additional ASR framework downloads

2026-10-27: official stable Windows x64 Vulkan archives installed and enabled in the [ASR updater catalog](../../scripts/download/frameworks/asr/updates.py).

| Component | Release | Executable relative to `frameworks/` |
| --- | --- | --- |
| NeMo-Speech.cpp | v0.2.0 | `asr/nemo-speechcpp/vulkan/bin/nemo-speech.exe` |
| speech.cpp | v0.9.0 | `asr/speechcpp/vulkan/speech.exe` |
| CrispASR | v0.8.45 | `asr/crispasr/vulkan/crispasr.exe` |
| FunASR llama.cpp runtime | v1.4.16 | `asr/funasr/vulkan/llama-funasr-sensevoice.exe` |

NeMo retains its vendor bin/lib layout. Other archives retain their runtime files beside the executable. No source build was needed. Sherpa remains installed once under `frameworks/tts/sherpa-onnx`; AudioCpp remains under its existing root because both also provide TTS.

All advertised archive SHA256 hashes verified; executable paths and updater markers checked. CLI help/model-catalog inspection subsequently passed outside the sandbox: AppContainer=false, administrator=false. No inference or service was started. Each installation has `INSTALL.json`; installation evidence in `scripts/state/logs/asr/shared/framework-downloads-1793159220414877900.json`.

```powershell
C:/AI/bat/update_frameworks.bat --category asr --check-only
C:/AI/bat/update_frameworks.bat --only asr/nemo-speechcpp
```

Remove `--check-only` to update all active ASR entries. NeMo uses stable releases; nightly is not selected. Source archives/download metadata are preserved under `scripts/state/cache/asr/shared/`.

Required models and launch profiles are now installed: [file-engine commands](../../scripts/launchers/asr/FILE-ENGINES.md). Catalog entries pin source revisions. Models/VAD assets total 2,844,284,199 bytes (2.85 GB); large-file SHA256s and all sizes verified against Hub metadata. Download identities/checksums in `scripts/state/logs/asr/shared/model-setup/downloaded-models.json`.

## Downloaded models

| Runtime | Selected weights |
| --- | --- |
| NeMo-Speech.cpp | Official Nemotron 3.5 Q8_0, 742 MB; runtime-pinned revision |
| speech.cpp | Packed Qwen3-ASR 0.6B Q8_0, 842 MB; Silero VAD |
| FunASR | SenseVoiceSmall Q8, 254 MB; FSMN-VAD |
| CrispASR | Reuses existing Whisper large-v3-turbo Q5_0; no new weights |
| Sherpa | English streaming Zipformer INT8 encoder/joiner, FP32 decoder and tokens, 73 MB |
| AudioCpp | Separate Nemotron 3.5 Q8_0 conversion, 931 MB; shared by Vulkan/ROCm |

Model-free checks and subsequent user-authorized native file inference pass. The initial approval rejection preceded the user's explicit test authorization. [Forty-case comparison and limits](ASR-COMPARISON.md); microphone/resident latency and gateway/browser integration remain [pending](../TODO.md). The [comparison runner](../../scripts/benchmarks/asr/asr_resident_compare.py) previews by default and requires `--run` for inference.

References: [NeMo model setup](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/v0.2.0/README.md#quick-start), [speech.cpp models](https://github.com/nyosegawa/speech.cpp/blob/v0.9.0/docs/models.md), [FunASR GGUF](https://github.com/modelscope/FunASR/blob/v1.4.16/runtime/llama.cpp/README.md), [CrispASR](https://github.com/CrispStrobe/CrispASR), [AudioCpp ASR](https://github.com/0xShug0/audio.cpp/blob/main/docs/asr.md).
