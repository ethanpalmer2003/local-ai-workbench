# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Reliability


## Standardization

- [ ] Decide the retired TTS pipeline in `scripts/launchers/audiocpp/tts_legacy_buffered.py`: nothing imports it, its own docstring calls it retired, and the active path is `tts_text_processing.py`. Delete it, or name the usefulness it still has; either way drop the `RETIRED` entry in `scripts/review/unused.py` with it. ~20 min
- [ ] Fetch the behind ComfyUI custom node again, and make that outcome visible: its updater runs in a detached console, so the failed fetch (`curl 18`, `early EOF` on a large repo) still left `comfyui/rocm` listed as updated in the framework summary. Re-run the updater; if the transfer fails again, fetch that node with a shallow clone or raise `http.postBuffer`. Record the vendor updater's exit status in the summary instead of assuming success. ~30 min
- [ ] Repair the Strata install: the native updater kept engine 0.1.59 because 0.1.60 failed its test start, while control reached 0.1.60, so a launch now exits before serving because the image encoder child cannot start (`WinError 5`). `update_frameworks` reports this and installs nothing; repair it in the Strata app (control reports `failed-before` for the engine) and confirm a plain launch serves without the vision-free config the benchmark used. ~20 min

## Needs a model run or device

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/benchmarks/asr/coverage.py). ~45-60 min

### Unattended

- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The Strata arm now passes `proverb` and `ledger` on all four clients (2026-11-15, engine 0.1.59 with control 0.1.60), but 27B has no run on `ledger`, so the pair needs the llama.cpp side. [Results](../scripts/tests/notes/OUTCOMES.md). ~1.5-2 h
