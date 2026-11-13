# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM.md), evidence in [STATUS](../scripts/tests/notes/STATUS.md).
- Each entry ends with a rough duration, shortest first.

## Reliability

- [ ] Nothing is waiting here. A defect that outlives its fix goes back on this list with the check that would have caught it.
- [ ] The no-model provider seed cannot work: `external_script` writes `kaihordewebui_*` keys, while Lite loads one `settings` record from the IndexedDB database `e_kaihordewebui_`. Either rewrite it to update that record once, or delete the seed and the `--external-endpoint` plumbing and let the page keep whatever provider is saved. ~30 min
- [ ] Make the slow checks cheaper, using the per-section log under `scripts/state/logs/shared/review/` rather than a fresh stopwatch. The leftover-package scan is 43 s of a 60 s gate: it walks every installed distribution and parses the tree for imports, so cache it against `uv.lock` plus the venv's `dist-info` timestamps and re-scan only on a mismatch. Types cost 10 s and everything else is under 2 s. The suite is 28 s, most of it per-module start-up, so a module filter would help more than a faster runner. ~45 min

## Needs a model run or device

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py). ~45-60 min

### Unattended

- [ ] Run the ROCm coding arm on b1375 now that the build hides the iGPU: `swift15` at 119.8 tok/s is the b1372 number to beat or match, and the mask itself needs a coding-sized load rather than a 26-token warmup. ~20 min
- [ ] Retest Kobold readiness and the remaining live targets after the integrity-label fix; its launcher still timed out at 180 s. ~30 min
- [ ] Run the Strata arm of the coding-engine benchmark from a normal terminal: under this harness the engine exits with "cannot create the refill stream" after the expert load, and the vision encoder fails with `WinError 5`. The llama.cpp arm is recorded. ~30-45 min
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h
