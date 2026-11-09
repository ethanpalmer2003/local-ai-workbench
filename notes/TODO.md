# TODO

- Work that will happen: the decision is made and the owner is linked. Undecided choices: [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Upstream defects and our responses: [UPSTREAM](UPSTREAM.md). Entries do not authorize live tests, package changes or long runs. [Status/evidence](../scripts/tests/notes/STATUS.md); procedures stay with their owner guides.

## Checks

- [ ] Run the full review (`python -m scripts.review`) after the current structural edits; ask before running it, since routine iteration only runs the failing module.

## Needs a model run

- [ ] Finish live voice-practice checks on both chat consumers: pipelining, microphone capture, playback and echo. Saved-PCM sequential ASR/chat/TTS passed on both; the browser mic returned audio requests but no transcript. Report (../scripts/tests/output/asr/shared/practice_smoke/unreviewed/1793511451717288800/artifacts/report.json) · [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md).
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. Every resident profile has a brief English check. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py).
- [ ] Gemma audio: one internal clip reaches the output limit under llama.cpp (KoboldCpp clean, WER 0). Shorten the clip or raise the token budget; the run records the failed clip instead of aborting.
- [ ] Refresh the capability rows that have not rerun since provenance was added; the launcher and llama.cpp context rows are already fresh.
- [ ] Kobold/Drama active-overlap baseline at the selected 40-layer/2048-context setup; measure simultaneous generation, queueing and playback underruns, then review listening, buffering, restart behavior and Lite patch rebase. [Procedure](../scripts/tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md). Drama tests remain deferred.
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md).
- [ ] llama.cpp: filled-context Vulkan/Lemonade comparison, medium/high-context speculation and short-context variation. Short-context is measured on Lemonade; Vulkan freezes on long generations and stays short ([draft](reviews/LLAMACPP-VULKAN-2026-11-09.md)). Filled-context and speculation variants are open.
- [ ] Publish a dated report for the Strata profile pair. The prefill arm measures cleanly; the decode arm stops on the run's own 1 GiB RAM floor because its expert cache commits the pack, so it needs a resident budget rather than an override.
- [ ] ComfyUI: validate promising 480 screens at 640 and longer clips, then publish a dated report for the 640 scaling claim, which kept no artifact; assess appearance, autotune/cache and monitor overhead; pinned memory is off with no recorded reason, so compare it on before keeping that default.

## Needs a device

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null (the default device) and the last attempt captured 0 samples in 17 ms, so the device is the suspect; the model, VAD and hotkey are configured.
