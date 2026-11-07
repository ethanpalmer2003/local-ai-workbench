# Native validation - 2026-10-27

Current scope: brief Breeze/Ming TTS checks; Ming enabled in the HTML page. No further Drama, broad launcher or long benchmark runs.

## AudioCpp releases and paths

- Both official GitHub packages are v0.9.3. Updater confirms current: `audiocpp/vulkan`, `audiocpp/rocm`.
- Executables live directly under `C:/AI/frameworks/audiocpp/{vulkan,rocm}/`. Vulkan's previous path preserved ZIP build nesting; future updates flatten it automatically, with regression coverage.
- Older ROCm variants moved under `audiocpp/additions/rocm/`; move manifest in `scripts/state/cache/audiocpp/short-paths-1793151217191775700/manifest.json`, old layout folders retained in trash.
- ROCm SHA256 matched GitHub/user value: `ca07ba49b7e63d9fc37eb911b451fc3d97956f09441cb08cac3ad6b16f7627df`.

## Brief Breeze result

[Evidence](../scripts/tests/output/audiocpp/audiocpp_backend_compare/inconclusive/1793151441243880200/artifacts/summary.json): one warmup and one measured short English sentence per build; same Q4 model, seed and prompt; sequential device-zero runs.

| Backend | Request seconds | Audio seconds | RTF | Sampled process GPU MiB |
| --- | ---: | ---: | ---: | ---: |
| Vulkan | 0.984 | 2.56 | 0.384 | 2775 |
| Official ROCm | 2.204 | 2.56 | 0.861 | 3673 |

- WAVs nonempty/non-silent; listening quality ungraded. One short sample does not establish a general ranking. Vulkan stays default.
- GPU values are sampled dedicated allocations, not precise physical residency. RAM/CPU traces and hashes are in the report.
- Approved outside sandbox; AppContainer false, administrator false. Each native probe records its context. AudioCpp proxy/native server are now left running for the user's test page at localhost:8888/test/.

## Setup and other completed checks

- Ming synthesis passed on both releases: Vulkan 0.740 s / 2.10 s audio; ROCm 0.862 s / 2.20 s audio. [Short-run evidence](../scripts/tests/output/audiocpp/audiocpp_backend_compare/inconclusive/1793151713638444700/artifacts/summary.json). One sample each, no quality ranking.
- Ming HTML catalog, voice cloning and SSE at 44100 Hz passed. [API evidence](../scripts/tests/output/audiocpp/ming_page_smoke/unreviewed/1793151979038233700/artifacts/report.md); actual browser completed with zero playback underruns. [Page screenshot](../scripts/tests/output/audiocpp/ming_page_smoke/unreviewed/1793151979038233700/artifacts/test-page.png).
- The heavier audio checkpoint (9.97 GB) is downloaded and registered in both releases and the live test-page catalog; offline WAV controls enforced. [Loader/catalog evidence](../scripts/tests/output/audiocpp/audiocpp_backend_compare/unreviewed/1793152699675709000/artifacts/report.md). Heavy synthesis not run.
- 284 model-free regressions pass; structure/docs, types and function-size checks pass.
- Earlier [native batch](../scripts/tests/output/shared/quick_validation/unreviewed/1793150687847258100/artifacts/report.md) passed rebuilt Whisper, Whisper/Qwen practice API/chat, Gemma including 30 seconds, Kokoro and images.
- Parakeet CPU/Vulkan/VAD [passed](../scripts/tests/output/asr/parakeetcpp/smoke/unreviewed/1793150513700310600/artifacts/report.md). Whisper b5454 rebuilt at relocated paths; previous installation preserved.
- Interrupted Drama work had finished before cancellation; evidence retained, no further runs. Browser/Handy, multilingual accuracy, active overlap and deeper comparisons remain in [TODO](TODO.md).
