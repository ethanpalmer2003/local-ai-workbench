# Retained TTS runtimes: Sherpa and Piper

Owned by [AudioCpp](README.md), the selected TTS framework; these two stay installed as comparison alternatives.

[All speech-model language lists/counts](../../config/notes/MODEL-LANGUAGES.md).

Retained alternatives; AudioCpp is the selected language-practice TTS framework.
Further Piper/Sherpa TTS integration/comparisons are not planned. This does not
change Sherpa ASR coverage.

Why selected: AudioCpp generated Kokoro faster than Sherpa and Kobold in our
brief checks, and supports the chosen speech models/integration. Piper's tested
Lessac voices were faster, but are different, English-only models; the user
deprioritized that lightweight route. This is not a universal speed or listening
quality ranking. [Matched Kokoro](../../tests/notes/KOKORO-PIPER-SCREEN.md) and
[four-runtime evidence](../../tests/notes/BRIEF-REALTIME-SCREEN.md) own the limits.

Official Windows x64 CPU installations:

| Component | Installation |
| --- | --- |
| `tts/sherpa-onnx` | `frameworks/tts/sherpa-onnx/` |
| `tts/piper` | `frameworks/tts/piper/` |

```powershell
C:/AI/bat/update_frameworks.bat --only tts --check-only
```

Remove `--check-only` to install/update. See the [updater guide](../../download/frameworks/UPDATES.md) for categories and replacement behavior.

AudioCpp is the selected TTS framework; Piper/Sherpa are retained alternatives
for benchmark comparison only. The interactive CLI wrapper was retired to
`C:/AI/trash/scripts-tests-old/tts_cli.py`. Sherpa retains its vendor
`bin/` and `lib/` layout; the downloaded package includes ASR executables too.
One installation serves both capabilities.

Piper uses the project Python with its wheel and dependencies isolated in the framework folder. The updater records resolved dependencies in `INSTALL.json`; it does not install them into the shared environment.

Lessac medium is shared by Piper/Sherpa; Lessac high is available for Piper under `models/tts/piper/lessac-high/`. Sherpa Kokoro v1.0 INT8 and its voice/token/English lexicon assets live under `models/tts/sherpa-onnx/kokoro-v1.0-int8/`. The canonical catalog owns pinned download sources. AudioCpp GGUF files are not interchangeable with these ONNX models.

Run the resident comparison with [benchmark_tts_speed.bat](../../../bat/benchmarks/benchmark_tts_speed.bat). Add `--engine piper --profile lessac-high` or `--engine sherpa-onnx --profile kokoro-v1.0-int8` to select the alternatives. It uses the shared benchmark lifecycle: voice loaded once, warmup excluded, WAV saving outside measured synthesis. Kokoro selects af_heart and five CPU threads. Its English lexicon does not establish French/Spanish frontend support. Further TTS framework comparisons are closed; [TODO](../../../notes/TODO.md) tracks AudioCpp model/voice follow-up.
