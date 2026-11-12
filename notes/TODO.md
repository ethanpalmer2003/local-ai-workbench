# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM.md), evidence in [STATUS](../scripts/tests/notes/STATUS.md).
- Each entry ends with a rough duration, shortest first.

## Reliability

- [ ] Nothing is waiting here. A defect that outlives its fix goes back on this list with the check that would have caught it.
- [ ] Optional: mark a row stale when its producer changed; `freshness()` compares builds, weights and corpus only. Fingerprint the producer. ~30 min

## Needs a model run or device

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py). ~45-60 min

### Unattended

- [ ] Retest llama.cpp coding on the ROCm build when a release newer than b1373 appears; b1373 aborts at startup with device -1, and b1372 is installed again. ~20 min
- [ ] Retest Kobold readiness and the remaining live targets after the integrity-label fix; its launcher still timed out at 180 s. ~30 min
- [ ] Run the Strata arm of the coding-engine benchmark from a normal terminal: under this harness the engine exits with "cannot create the refill stream" after the expert load, and the vision encoder fails with `WinError 5`. The llama.cpp arm is recorded. ~30-45 min
- [ ] llama.cpp: medium/high-context speculation. Filled context at 32k is measured: cold prefill 505 tok/s with a 63.3 s TTFT, 48.5 tok/s decode warm at 12.8 GiB. Vulkan freezes on long generations ([draft](reviews/LLAMACPP-VULKAN-2026-11-09.md)). ~1-1.5 h
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h
