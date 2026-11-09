# Language practice

- Chat: Gemma 4 E4B Q4_0. Default ASR: AudioCpp Nemotron (`audiocpp-nemotron`). Default TTS: Kokoro multilingual, no cloning. These follow the `LANGUAGE_PRACTICE` workflow profile in [launcher_config.py](../../launchers/launcher_config.py).
- Canonical commands, implementations and limits: [ASR guide](../../launchers/asr/README.md).
- Shared weights: Gemma main/projector under `models/llms/multilingual_models`; ASR-specific weights under `models/asr/<framework>`; Kokoro packages under `models/audiocpp`.

## Qwen3-ASR alternative through llama.cpp

- `QWEN3_ASR` uses Q8_0 main/projector through the shared Vulkan llama.cpp install. Named Qwen batches exist for both chat consumers.
- Prior two-clip API integration passed; it was clean English, not multilingual quality evidence. Saved run (../../tests/output/probes/language_practice_whisper/unreviewed/1793082524839352700/artifacts/report.json).

## Current standalone Whisper experiments

- Build/update explicitly with `bat/update_frameworks.bat --only asr/whispercpp/vulkan-build`; add `--check-only` to report revisions.
- Requires Visual Studio C++ Build Tools, CMake, Ninja and `VULKAN_SDK`; no CPU Whisper package selected.
- Installs: `frameworks/asr/whispercpp/{vulkan-build,vulkan}`; legacy community Vulkan remains disabled/retained for comparison.
- Model: the whisper.cpp turbo entry in the catalog; the smaller entries trade accuracy for speed.

## Whisper embedded versus installed standalone

- Existing runner: `scripts.benchmarks.asr.whisper_embedded_compare`; current FA and legacy variants use identical weights.
- Kobold's embedded implementation has separate hardcoded settings; general LLM FA/thread switches do not configure its Whisper decoder.

## Initial Whisper results 2026-10-26

- Prior ABBA screen: matching clean synthetic transcripts, 32 requests. Results (../tests/output/probes/whisper_embedded_compare/unreviewed/1793071343555664800/artifacts/report.json).
- Current FA sample: about 875 MiB loaded, 922 MiB sampled peak; budget approximately 1 GiB. Sampled, model-specific, not a general cap.

## Benchmarks

- Kokoro internal/external packages differ in format and quantization; compare full configurations, not engine-only speed.
- External Kokoro uses portable eSpeak at `frameworks/audiocpp/additions/espeak-ng`; `KOKORO_TTS` owns its profile.
- Gemma audio worked in both runtimes before refactoring, including 30-second clips; reasoning/KV/cache conditions were not matched for a fair speed ranking.
- [Coding checkpoint/deferred validation](../../../notes/asr/ASR-IMPLEMENTATION.md). No automatic tests/benchmarks; preserve existing sessions and execution-context evidence.
