# TODO

- Work that will happen: the decision is made and the owner is linked. Open choices are under [Questions](#questions); settled ones in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Upstream defects and our responses: [UPSTREAM](UPSTREAM.md). Entries do not authorize live tests, package changes or long runs. [Status/evidence](../scripts/tests/notes/STATUS.md); procedures stay with their owner guides.

## Checks

- [ ] Run the full review (`python -m scripts.review`) after the current structural edits; ask first, since routine iteration runs only the failing module.

## Needs a model run

- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md).
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py).
- [ ] Gemma audio: keep the 512-token budget and the recorded failed clip. Raising the limit would mask the loop, and shortening the clip cannot help because the model loops on a short utterance, not the 30 s stress clip. Revisit if a build changes the behaviour.
- [ ] Refresh the capability rows that have not rerun since provenance; the launcher and context rows are fresh.
- [ ] Kobold/Drama active-overlap: deferred, not planned. A 15.9 GiB local TTS model plus generation is heavier than this setup should carry, so the retired idle screen stays retired and no overlap harness is built. Revisit only if the model gets smaller.
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md).
- [ ] llama.cpp: medium/high-context speculation. Filled context at 32k is measured: cold prefill 505 tok/s with a 63.3 s TTFT, 48.5 tok/s decode warm and 39.0 tok/s cached at 12.8 GiB. Vulkan freezes on long generations ([draft](reviews/LLAMACPP-VULKAN-2026-11-09.md)).
- [ ] Publish a dated report for the Strata profile pair. Both arms now run: the decode profile carries an 8 GiB resident budget, and the replay measured prefill ahead on decode and prompt read. Write the numbers up as a screen, not a ranking.
- [ ] ComfyUI: 640 measured at 5 s (14.4 GiB) and 10 s (241 frames, 231-244 s, 16.0 GiB, near the card limit). Pinned memory tested: on is slower and uses more VRAM, so it stays off. Remaining: a dated report, appearance review, autotune/cache and monitor overhead.

## Needs a device

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured.

## Questions

### Tooling

- Capability matrix: rerun the 28 rows still unprovenanced, wiring each producer as it is touched, or keep the three fresh rows only?
