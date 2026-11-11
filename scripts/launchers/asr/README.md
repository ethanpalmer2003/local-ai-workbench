# ASR and language practice

- [Speech workspace](PRACTICE-WORKSPACE.md) covers routes, conversation and measurements; [interactive speech-model selection](PRACTICE-MODELS.md) covers ASR framework/model and TTS model choice.

- [Picks and reasons](../../../notes/asr/ASR-EVALUATION.md); [language lists/counts](../../config/notes/MODEL-LANGUAGES.md).
- [All profiles grouped by streaming/VAD](CAPABILITIES.md); [evaluation and saved speeds](../../tests/notes/asr/ASR-SCREEN.md).
- [Multi-use layouts](MULTIUSE.md): shared Gemma, multiple AudioCpp/llama.cpp servers, concurrency limits and staged test matrix.

| Backend | Code / settings | Scope |
| --- | --- | --- |
| AudioCpp Nemotron + Silero | `audiocpp/asr.py`, `AUDIOCPP_VAD` | Default practice ASR; shares Kokoro server |
| NeMo Nemotron Vulkan | `NEMO_SPEECHCPP_ASR` | Stateful streaming, shared Silero turns |
| Parakeet Nemotron CPU | `PARAKEETCPP_STREAM_ASR` | Stateful C API streaming; [setup](NEMOTRON-STREAMING.md) |
| speech.cpp Qwen 0.6B | `SPEECHCPP_ASR` | Automatic Silero turns, resident Vulkan decoder |
| Whisper Vulkan + Flash Attention | `whispercpp/server.py`, `WHISPERCPP_ASR` | Automatic Silero turns |
| Parakeet v3 Vulkan | `PARAKEETCPP_V3_ASR` | Automatic Silero turns, automatic language detection |
| Qwen3-ASR | `llamacpp/qwen3_asr.py`, `QWEN3_ASR` | llama.cpp ASR service |
| Gemma audio | `llamacpp/gemma_audio.py`, `GEMMA_AUDIO_ASR` | Prompted audio chat, shared weights |
| Kobold Gemma | `koboldcpp/gemma_audio.py` | Uses loaded Kobold chat model |
| Parakeet CPU/Vulkan | [setup](PARAKEET.md), `PARAKEETCPP_ASR` | 110M file CLI; v3 gateway available |
| Handy | [setup](HANDY.md) | Portable desktop dictation |
| Additional ASR runtimes | [file engines](FILE-ENGINES.md) | NeMo, speech.cpp and AudioCpp; required models downloaded |

- `ASR_SERVICE` owns shared gateway selection/port. External ASR works with either chat consumer.
- Installs/models use `asr/<framework>/`; shared Gemma weights and chat runtimes remain single assets.
- `shared/turns.py` owns VAD/pre-roll; `segment_stream.py` adapts resident completed-turn decoders. Native startup uses `launchers/shared/services/native.py`; `llamacpp/llama_audio.py` owns the shared llama.cpp audio-server command and startup.

## Launch

```powershell
C:/AI/bat/browser/launch_language_kobold.bat
C:/AI/bat/browser/launch_language.bat
C:/AI/bat/browser/launch_test_asr.bat
```

- Select alternatives with `--transcription-engine` (streaming: `nemo-nemotron`, `parakeetcpp-nemotron-cpu`; completed-turn: `speechcpp-qwen-0.6b`, `whisper-vulkan`, `parakeetcpp-v3`); Kokoro stays Vulkan; the configured engine comes from `ASR_SERVICE`.
- Kobold Gemma audio profile shares its loaded model; standalone Gemma ASR plus Kobold chat loads two instances. Direct llama.cpp Gemma can share one server for chat/audio.
- Common `/practice` page: automatic microphone turns with the default backend, WAV upload, transcript editing, Gemma chat and Kokoro playback. NeMo, Parakeet CPU Nemotron, Qwen 0.6B, Whisper and Parakeet v3 support automatic turns. `--practice-ui` selects it for Kobold.
- External API, language options and service limits: [ASR language options, external API and limits](README-LANGUAGES-API-LIMITS.md).
- [Test organization](../../tests/cases/asr/README.md), [implementation and deferred work](../../../notes/asr/ASR-IMPLEMENTATION.md). No new inference/testing authorized by this guide.
