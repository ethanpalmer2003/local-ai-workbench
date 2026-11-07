# TODO

- Pending work only. Entries do not authorize live tests, package changes, or long runs.
- [Status/evidence](../scripts/tests/notes/STATUS.md); procedures stay with their owner guides.

## Voice and ASR

- [ ] Finish live voice-practice checks on both chat consumers: pipelining/interruption, microphone capture, playback and echo. Saved-PCM sequential ASR/chat/TTS passed on both; AudioCpp ASR resources sampled (2026-10-31). Browser mic session returned audio requests but no transcript; no spoken-input result. [Report](../scripts/tests/output/asr/shared/practice_smoke/unreviewed/1793511451717288800/artifacts/report.json) · [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md).
- [ ] Measure multilingual/noisy accuracy and real microphone latency; browser model/API routes responded, but capture produced no transcript. No multilingual/noisy reference corpus is configured. All 16 resident profiles have brief synthetic-English checks; decide whether CrispASR/FunASR need resident adapters. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py).
- [ ] Validate Handy microphone selection, dictation and paste. UI shows Default microphone and Average all channels; no dictation or paste was tested.

## Code quality

- [ ] The lint config never sees the updater tree. `[tool.ruff] extend-exclude` (and `[tool.deptry] exclude`) list the bare name `frameworks`, which also matches `scripts/download/frameworks/`; anchor it as `/frameworks` (as `.gitignore` and the codespell hook already do). That exposes 18 real findings: 8 `I001` import orders, 1 `S101` `assert` in `restrict_specspeed`, and 9 functions over McCabe 10 (`process_source` 20, `stop_installation_processes` 19, `package_audiocpp_hip` 13, `process_bat` 13, `read_ninja_log` 12, `process_tool` 12, `process` 11, `process_audiocpp_hip` 11, `run` 11). Fix the config and burn those down together, then re-check `COMPLEXITY-DEBT.md`.

## Deferred

- [ ] Kobold/Drama active-overlap baseline at the selected 40-layer/2048-context setup; measure simultaneous generation, queueing and playback underruns, then review listening, buffering, restart behavior and Lite patch rebase. [Procedure](../scripts/tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md). Drama tests remain deferred.
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md).
- [ ] llama.cpp: filled-context Vulkan/Lemonade comparison, medium/high-context speculation and short-context variation.
- [ ] hipfire/TabbyAPI: validate on a Linux/ROCm host, convert the Swift checkpoint to MQ4/EXL3. The `benchmark_llm_inference` sweep was retired to `C:/AI/trash/retired-llm-inference-sweep`; restore or rebuild it first. Windows is unsupported; no model downloads were added.
- [ ] Retest Parakeet Nemotron Vulkan streaming after an upstream fix; streaming remains disabled after a crash. Keep CPU/GPU and offline/streaming results separate.
- [ ] HRX IQ3_XXS/kernel/register analysis and latest-source build. Native and long runs need approval. [HRX guide](../scripts/config/llamacpp/HRX.md).
- [ ] ComfyUI: validate promising 480 screens at 640 and longer clips; assess appearance, autotune/cache and monitor overhead. Smart-memory retest is low priority.
