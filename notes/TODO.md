# TODO

- Pending work only. Entries do not authorize live tests, package changes, or long runs.
- [Status/evidence](../scripts/tests/notes/STATUS.md); procedures stay with their owner guides.

## Voice and ASR

- [ ] Finish live voice-practice checks on both chat consumers: pipelining/interruption, microphone capture, playback and echo. Saved-PCM sequential ASR/chat/TTS passed on both; AudioCpp ASR resources sampled (2026-10-31). Browser mic session returned audio requests but no transcript; no spoken-input result. [Report](../scripts/tests/output/asr/shared/practice_smoke/unreviewed/1793511451717288800/artifacts/report.json) · [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md).
- [ ] Measure multilingual/noisy accuracy and real microphone latency; browser model/API routes responded, but capture produced no transcript. No multilingual/noisy reference corpus is configured. All 16 resident profiles have brief synthetic-English checks; decide whether CrispASR/FunASR need resident adapters. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py).
- [ ] Validate Handy microphone selection, dictation and paste. UI shows Default microphone and Average all channels; no dictation or paste was tested.

## Code quality

- [ ] `kobold_stack_vram.generate` returns the *input* prompt text for the audio and image kinds, not a result. Only the text caller consumes it; decide whether the other kinds should return `""`.
- [ ] Dependency advisories: `python -m scripts.review --audit` reports 80 across 11 packages (pillow 39, filelock 12, transformers 9, aiohttp 8). Third-party and mostly transitive; triage what is reachable, then decide whether any pin moves.
- [ ] `benchmark_context_stream.stream_request` reads `events[0]["seconds"]`, so a stream with no token events raises `IndexError` instead of a clear contract error.
- [ ] `kobold_image_swap._swap_cycles` passes `lambda: generate(..., label)` with the loop variable bound late; it only works because `record` calls it immediately. Bind `label` as a default argument.

## Deferred

- [ ] Kobold/Drama active-overlap baseline at the selected 40-layer/2048-context setup; measure simultaneous generation, queueing and playback underruns, then review listening, buffering, restart behavior and Lite patch rebase. [Procedure](../scripts/tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md). Drama tests remain deferred.
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md).
- [ ] llama.cpp: filled-context Vulkan/Lemonade comparison, medium/high-context speculation and short-context variation.
- [ ] hipfire/TabbyAPI: validate on a Linux/ROCm host, convert the Swift checkpoint to MQ4/EXL3. The `benchmark_llm_inference` sweep was retired to `C:/AI/trash/retired-llm-inference-sweep`; restore or rebuild it first. Windows is unsupported; no model downloads were added.
- [ ] Retest Parakeet Nemotron Vulkan streaming after an upstream fix; streaming remains disabled after a crash. Keep CPU/GPU and offline/streaming results separate.
- [ ] HRX IQ3_XXS/kernel/register analysis and latest-source build. Native and long runs need approval. [HRX guide](../scripts/config/llamacpp/HRX.md).
- [ ] ComfyUI: validate promising 480 screens at 640 and longer clips; assess appearance, autotune/cache and monitor overhead. Smart-memory retest is low priority.
