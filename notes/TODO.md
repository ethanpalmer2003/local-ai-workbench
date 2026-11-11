# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM.md), evidence in [STATUS](../scripts/tests/notes/STATUS.md).
- Each entry ends with a rough duration, shortest first.

## Reliability

- [ ] Nothing is waiting here. A defect that outlives its fix goes back on this list with the check that would have caught it.

## Needs a model run or device

### Requires user input

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py). ~45-60 min

### Unattended

- [ ] Compare the practice stack with Lemonade on one of its MOSS TTS entries instead of `kokoro-v1`; that removes the Lemonade leg as a reason to keep Kokoro installed. Needs the Lemonade model download first. ~30-45 min
- [ ] Decide whether Lemonade qualifies as a voice-design framework now that `MOSS-VoiceGen` is in its catalog; allowing it for the character profile needs a test, not just the label. ~20-30 min
- [ ] Retest llama.cpp coding on the ROCm build when a release newer than b1373 appears; b1373 aborts at startup with device -1, and b1372 is installed again. ~20 min
- [ ] Retest Kobold readiness and the remaining live targets after the integrity-label fix; its launcher still timed out at 180 s. ~30 min
- [ ] Run the coding-engine benchmark on llama.cpp and Strata for the first comparable prefill, decode and TTFT rows: `--engine llamacpp --profile swift15`, then `--engine endpoint` against a running Strata. It starts servers itself and needs free ports. ~30-45 min
- [ ] llama.cpp: medium/high-context speculation. Filled context at 32k is measured: cold prefill 505 tok/s with a 63.3 s TTFT, 48.5 tok/s decode warm and 39.0 tok/s cached at 12.8 GiB. Vulkan freezes on long generations ([draft](reviews/LLAMACPP-VULKAN-2026-11-09.md)). ~1-1.5 h
- [ ] Rerun the capability rows so their recorded evidence is judged: 23 are flagged, and each run turns its row green or names what changed. `python -m scripts.tools.capability_matrix --check` lists them. ~1-2 h
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h
