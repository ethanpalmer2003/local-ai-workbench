# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Reliability


## Standardization

- [ ] Decide the retired TTS pipeline in `scripts/launchers/audiocpp/tts_legacy_buffered.py`: nothing imports it, its own docstring calls it retired, and the active path is `tts_text_processing.py`. Delete it, or name the usefulness it still has; either way drop the `RETIRED` entry in `scripts/review/unused.py` with it. ~20 min
- [ ] Re-run both similarity modes: documents last ran 2026-11-10 22:15 and code 21:56. The 2026-11-15 retry embeds for a few dozen units and then the llama.cpp b12421 Vulkan server resets the connection, on CPU as well as GPU, so it is blocked until that engine changes rather than a harness fix. `review_document_similarity.bat` and `review_code_similarity.bat`. ~15 min
- [ ] Repair the Strata install: the updater kept engine 0.1.59 because the 0.1.60 test start failed, while control went to 0.1.60, which then cannot spawn its image encoder (`WinError 5`) and exits before serving. Run the downloaded `Strata-0.2.14-windows-x64-setup.exe` by hand, or retry `strata update --force`, then launch once and confirm the agent benchmark starts without the vision-free config workaround. ~20 min

## Needs a model run or device

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/benchmarks/asr/coverage.py). ~45-60 min

### Unattended

- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The Strata arm now passes `proverb` and `ledger` on all four clients (2026-11-15, engine 0.1.59 with control 0.1.60), but 27B has no run on `ledger`, so the pair needs the llama.cpp side. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h
