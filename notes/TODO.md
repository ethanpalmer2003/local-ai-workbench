# TODO

- Work that will happen: the decision is made and the owner is linked. Open choices are listed under [Questions](#questions) below; settled decisions stay in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Upstream defects and our responses: [UPSTREAM](UPSTREAM.md). Entries do not authorize live tests, package changes or long runs. [Status/evidence](../scripts/tests/notes/STATUS.md); procedures stay with their owner guides.

## Checks

- [ ] Run the full review (`python -m scripts.review`) after the current structural edits; ask first, since routine iteration runs only the failing module.

## Needs a model run

- [ ] Finish live voice-practice checks on both chat consumers: pipelining, microphone capture, playback and echo. Saved-PCM path passes on both; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md).
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py).
- [ ] Gemma audio: one internal clip reaches the output limit under llama.cpp (KoboldCpp clean, WER 0). Shorten the clip or raise the token budget; a failed clip is recorded, not fatal.
- [ ] Refresh the capability rows that have not rerun since provenance; the launcher and context rows are fresh.
- [ ] Kobold/Drama active-overlap baseline at the selected 40-layer/2048-context setup: no harness exists. The idle-only screen is retired, refuses to run without `--idle-residency`, and never overlapped generation, so this needs a measurement mode first. [Procedure](../scripts/tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md).
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md).
- [ ] llama.cpp: medium/high-context speculation, plus a cold filled-context prefill number (the 32k sample reuses its cached prompt; decode is 39.0 tok/s at 12.8 GiB). Short-context decode is measured on Lemonade; Vulkan freezes on long generations ([draft](reviews/LLAMACPP-VULKAN-2026-11-09.md)).
- [ ] Publish a dated report for the Strata profile pair. Prefill measures cleanly; the decode arm stops on the run's own 1 GiB RAM floor because its expert cache commits the pack, so it needs a resident budget.- [ ] ComfyUI: 640 measured at 5 s (14.4 GiB) and 10 s (241 frames, 231-244 s, 16.0 GiB, near the card limit). Pinned memory tested: on is slower and uses more VRAM, so it stays off. Remaining: a dated report, appearance review, autotune/cache and monitor overhead.

## Needs a device

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null (the default device) and the last attempt captured 0 samples in 17 ms, so the device is the suspect; the model, VAD and hotkey are configured.

## Questions

- Strata decode profile: give it an explicit resident budget (8-10 GiB) and rerun the pair, or leave the tuning alone?
- Kobold/Drama overlap: build the active-overlap harness (simultaneous generation, queueing, playback underruns), or keep it deferred?
- Gemma audio: shorten the clip that hits the output limit, or raise its token budget?
- Capability matrix: rerun the 28 rows still unprovenanced, wiring each producer as it is touched, or keep the three fresh rows only?
