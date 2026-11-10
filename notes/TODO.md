# TODO

- Work that will happen: the decision is made and the owner is linked. Open choices are under [Questions](#questions); settled ones in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM.md), evidence in [STATUS](../scripts/tests/notes/STATUS.md).
- Each entry ends with a rough duration, shortest first.

## Needs a model run or device

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py). ~45-60 min
- [ ] llama.cpp: medium/high-context speculation. Filled context at 32k is measured: cold prefill 505 tok/s with a 63.3 s TTFT, 48.5 tok/s decode warm and 39.0 tok/s cached at 12.8 GiB. Vulkan freezes on long generations ([draft](reviews/LLAMACPP-VULKAN-2026-11-09.md)). ~1-1.5 h
- [ ] Refresh the capability rows that have not rerun since provenance; the launcher and context rows are fresh. ~1-2 h
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h

## Questions

### Tooling

- Capability matrix: rerun the 28 rows still unprovenanced, wiring each producer as it is touched, or keep the three fresh rows only?
