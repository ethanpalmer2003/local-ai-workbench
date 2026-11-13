# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM.md), evidence in [STATUS](../scripts/tests/notes/STATUS.md).
- Each entry ends with a rough duration, shortest first.

## Reliability

- [ ] Nothing is waiting here. A defect that outlives its fix goes back on this list with the check that would have caught it.
- [ ] Rewrite the no-model provider seed, which external-LLM mode needs: KoboldCpp then runs without a model, so the page has to be pointed at llama-server or generation fails until someone picks the custom provider by hand. `external_script` writes `kaihordewebui_*` localStorage keys while Lite reads one `settings` record from the IndexedDB database `e_kaihordewebui_`, so seed that record once instead. The patch needs the live page: save one with `kobold_lite --export-html` during the next session and reuse it through `--source-file`. ~30 min

## Needs a model run or device

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py). ~45-60 min

### Unattended

- [ ] Run the coding arm on both builds through the fixed harness: the 2026-11-13 quick screen was one sample of 128 tokens and the older rows pooled their warm-up, so neither ranks the builds on decode. Three samples per task now that a warm-up request precedes them. ~20 min
- [ ] Shorten the coding arm: four tasks share one three-thousand-token prefix and a 128-token answer, so they repeat the same measurement while adding a task-specific suffix. Two tasks (one implementation, one refactor) with three samples carry the same signal for half the run, and a second context size would test what the tasks do not. ~15 min
- [ ] Retest Kobold readiness and the remaining live targets after the integrity-label fix; its launcher still timed out at 180 s. ~30 min
- [ ] Run the Strata arm of the coding-engine benchmark from a normal terminal: under this harness the engine exits with "cannot create the refill stream" after the expert load, and the vision encoder fails with `WinError 5`. The llama.cpp arm is recorded. ~30-45 min
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h
