# TODO

- Work that will happen: the decision is made and the owner is linked. Undecided choices: [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. [Status/evidence](../scripts/tests/notes/STATUS.md); procedures stay with their owner guides.

## Needs a model run

- [ ] Finish live voice-practice checks on both chat consumers: pipelining, microphone capture, playback and echo. Saved-PCM sequential ASR/chat/TTS passed on both; the browser mic returned audio requests but no transcript. [Report](../scripts/tests/output/asr/shared/practice_smoke/unreviewed/1793511451717288800/artifacts/report.json) · [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md).
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. Every resident profile has a brief English check; decide whether FunASR needs a resident adapter. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/tests/cases/asr/shared/coverage.py).
- [ ] Re-test AudioCpp Nemotron streaming for Japanese after an upstream build change: it closed the stream or reset the connection for every FLEURS `ja` clip although its card lists `ja-JP` as transcription-ready. The language profile now recognises through Whisper Vulkan, so this is a candidate engine, not the default. [Report](../scripts/benchmarks/output/shared/framework_compare/unreviewed/1794102411976669000/artifacts/report.json).
- [ ] Refresh the capability matrix once the stack settles; most entries are stale.
- [ ] Kobold/Drama active-overlap baseline at the selected 40-layer/2048-context setup; measure simultaneous generation, queueing and playback underruns, then review listening, buffering, restart behavior and Lite patch rebase. [Procedure](../scripts/tests/notes/audiocpp/AUDIOCPP-OPTIMIZATIONS.md). Drama tests remain deferred.
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The easy paired task is complete. [Results](../scripts/tests/notes/OUTCOMES.md).
- [ ] llama.cpp: filled-context Vulkan/Lemonade comparison, medium/high-context speculation and short-context variation.
- [ ] Retest Parakeet Nemotron Vulkan streaming after an upstream fix; it stays disabled after a crash. Keep CPU/GPU and offline results separate.
- [ ] HRX IQ3_XXS/kernel/register analysis and latest-source build. Native and long runs need approval. [HRX guide](../scripts/config/llamacpp/HRX.md).
- [ ] Publish a dated report for the Strata profile pair: the runs on disk are aborted stubs, so the recorded numbers need a rerun first.
- [ ] ComfyUI: validate promising 480 screens at 640 and longer clips, then publish a dated report for the 640 scaling claim, which kept no artifact; assess appearance, autotune/cache and monitor overhead.

## Needs a device

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null (the default device) and the last attempt captured 0 samples in 17 ms, so the device is the suspect; the model, VAD and hotkey are configured.

## Code and docs only

- [ ] Lemonade's Kokoro mis-speaks French and Japanese: its espeak-ng data ships `fr` and `ja` dictionaries, but `koko.exe` defaults to `-l en-us` and English styles, so its kokoro recipe maps language and style wrongly. File [the draft](reviews/UPSTREAM-KOKORO-2026-11-08.md). [Report](../scripts/benchmarks/output/shared/framework_compare/unreviewed/1794123067862277200/artifacts/report.json).
- [ ] KoboldCpp's Kokoro returns an empty WAV for Japanese and an English fallback elsewhere: the build embeds only `kokoro_ipa.embd`, so no other language has a phonemizer. File [the draft](reviews/UPSTREAM-KOKORO-2026-11-08.md). [Report](../scripts/benchmarks/output/shared/framework_compare/unreviewed/1794123067862277200/artifacts/report.json).
