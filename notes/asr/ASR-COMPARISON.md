# ASR comparison checkpoint

2026-10-27. User explicitly authorized native testing after the initial implementation-only approval rejection.

- Seven profiles, ten supported engine/mode combinations, two identical synthetic English clips (5.3 and 11.5 seconds), two trials per clip: **40 completed samples, zero failures**. Whole run 62.4 seconds.
- Comparison table (../../scripts/tests/output/asr/shared/cli_compare/unreviewed/1793160809243462800/artifacts/comparison.md), raw results/model hashes/context (../../scripts/tests/output/asr/shared/cli_compare/unreviewed/1793160809243462800/artifacts/report.json), CSV (../../scripts/tests/output/asr/shared/cli_compare/unreviewed/1793160809243462800/artifacts/summary.csv).
- Approved outside-sandbox execution, actual token AppContainer=false, administrator=false. Vulkan0 selected for NeMo, speech.cpp, FunASR, CrispASR and AudioCpp Vulkan; AudioCpp ROCm uses RX 7800 XT gfx1101; Sherpa uses CPU, four threads. Backend evidence stays in each sample's stderr log.

FunASR/SenseVoice was fastest in startup-inclusive offline file checks; speech.cpp/Qwen3-ASR was next. AudioCpp Vulkan/Nemotron was fastest among the tested stateful streaming-file paths. This is a comparison of complete model/runtime configurations, with different weights, quantization implementations and thread policies.

Each sample starts a fresh CLI and loads weights. An initial one-clip screen preceded the repeated run; OS/shader caches were not cleared. These results do not establish resident-model latency, fully cold startup, first-partial latency, paced real-time behavior or RAM/VRAM peaks. Existing servers were not restarted. No microphone recording occurred.

Coverage is six frameworks/seven build profiles, not the entire installed ASR collection. Parakeet and several existing runtime paths were absent. The [selection/coverage audit](ASR-EVALUATION.md) identifies missing models and the required resident-model benchmark.

Every configuration has the same pooled literal WER, 4%. The short clip differs in `practise`/`practice`; the longer clip has `cafe` versus `caf`/`calf`. Two clean synthetic clips cannot rank real-world or multilingual accuracy.

Sherpa's first screen recognized speech but failed extraction: this Windows CLI writes its recognition JSON to stderr. The parser now reads that stream; all repeated Sherpa cases pass. Initial failed evidence remains under run `1793160718443868800`. Model-free tests cover this stderr path and weighted error aggregation.

Procedures: [comparison guide](../../scripts/tests/cases/asr/COMPARISON.md), [launch commands](../../scripts/launchers/asr/FILE-ENGINES.md). Further work: [TODO](../TODO.md).
