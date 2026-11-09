# TODO

- Work that will happen: the decision is made and the owner is linked. Undecided choices: [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Upstream defects and our responses: [UPSTREAM](UPSTREAM.md). Entries do not authorize live tests, package changes or long runs. [Status/evidence](../scripts/tests/notes/STATUS.md); procedures stay with their owner guides.

## Checks

- [ ] Run the full review (`python -m scripts.review`) after the current structural edits; ask before running it, since routine iteration only runs the failing module.

## Needs a model run

- [ ] Finish live voice-practice checks on both chat consumers: pipelining, microphone capture, playback and echo. Saved-PCM sequential ASR/chat/TTS passed on both; the browser mic returned audio requests but no transcript. Report (../scripts/tests/output/asr/shared/practice_smoke/unreviewed/1793511451717288800/artifacts/report.json) · [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md).
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. Every resident profile has a brief English check. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py).
- [ ] Gemma audio: the current Q4_0 weights with the Q8_0 projector reach the output limit on one internal clip under llama.cpp (KoboldCpp is clean, WER 0). Decide whether to shorten that clip or raise the token budget; the comparison now records the failed clip instead of aborting. Summary: `scripts/benchmarks/output/asr/gemma_audio_compare/unreviewed/1794267231938431500/artifacts/summary.json`.
- [ ] Refresh the capability matrix once the stack settles. Most rows say `unprovenanced`, not stale: only three runners record provenance, so the matrix cannot judge the rest. Fix is one provenance hook in the shared report writer, then a rerun of the rows that matter.
- [ ] Kobold/Drama active-overlap baseline at the selected 40-layer/2048-context setup; measure simultaneous generation, queueing and playback underruns, then review listening, buffering, restart behavior and Lite patch rebase. [Procedure](../scripts/tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md). Drama tests remain deferred.
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md).
- [ ] llama.cpp: filled-context Vulkan/Lemonade comparison, medium/high-context speculation and short-context variation. Short-context at 8192/256 is measured on Lemonade (53.6, 43.4 and 51.6 tok/s, TTFT 0.26-0.28 s, 11.3 GiB peak). Vulkan freezes on the fourth 256-token generation at 4k and 8k, with two profiles, and passes five 32-token generations, so the comparison needs the Lemonade build for long runs; see [UPSTREAM](UPSTREAM.md). Filled-context and speculation variants are still open.
- [ ] Publish a dated report for the Strata profile pair: the runs on disk are aborted stubs, so the recorded numbers need a rerun first. The prefill arm now measures cleanly (44-45 tok/s decode, 353 tok/s prefill, TTFT 8.6 s, 38 s startup), but the decode arm stops on the run's own RAM floor (0.86-0.91 GiB free during startup, floor 1.0): its auto expert cache commits the pack instead of leaving the page cache reclaimable. Next step is a resident budget or a deliberate floor for that arm, not an unattended override.
- [ ] ComfyUI: validate promising 480 screens at 640 and longer clips, then publish a dated report for the 640 scaling claim, which kept no artifact; assess appearance, autotune/cache and monitor overhead; pinned memory is off with no recorded reason, so compare it on before keeping that default.

## Needs a device

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null (the default device) and the last attempt captured 0 samples in 17 ms, so the device is the suspect; the model, VAD and hotkey are configured.
