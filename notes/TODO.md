# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Reliability


## Standardization

- [ ] Decide the retired TTS pipeline in `scripts/launchers/audiocpp/tts_legacy_buffered.py`: nothing imports it, its own docstring calls it retired, and the active path is `tts_text_processing.py`. Delete it, or name the usefulness it still has; either way drop the `RETIRED` entry in `scripts/review/checks/dead_code.py` with it. ~20 min
- [ ] Roll the llama.cpp Vulkan build back: b12422 kills the 27B server while re-prefilling a 3,707-token prompt, so the coding model and the 27B benchmark arm do not run on it ([builds](../scripts/config/llamacpp/BUILDS.md)). Reinstall b12363, confirm one Pi `proverb` run finishes, then finish the Strata/27B pair on that tag. ~30 min
- [ ] Repair the Strata install: the native updater kept engine 0.1.59 because 0.1.60 failed its test start, while control reached 0.1.60, so a launch now exits before serving because the image encoder child cannot start (`WinError 5`). `update_frameworks` reports this and installs nothing; repair it in the Strata app (control reports `failed-before` for the engine) and confirm a plain launch serves without the vision-free config the benchmark used. ~20 min
- [ ] Judge the duplicate blocks the baseline still holds: `matching_server` is four identical one-liners (`whispercpp/server`, `embeddings/server`, `audiocpp/asr`, `asr/llamacpp/llama_audio`), `audiocpp.py::main` against `llamacpp.py::main` is two launchers with different wiring, and `launcher_config.py` carries the same three-line `exe` property on three build classes. Fold the one-liners if the wrapper is not the seam a test patches; leave the other two. [code pairs](../scripts/review/SIMILARITY.md). ~30 min
- [ ] Wire `python -m scripts.review.checks.duplicates` into an opt-in batch and settle its baseline granularity: it records a file pair plus a block count, so a second block in a known pair fails while a moved block does not. pylint needs about a minute over `scripts`. ~30 min
- [ ] Move the `codebase-memory-mcp` uv tool to Python 3.14 (`uv tool install --python 3.14 codebase-memory-mcp --force`), then uninstall the managed 3.13 interpreter; the tool currently runs on `cpython-3.13-windows-x86_64-none`, which blocked `uv python uninstall 3.13`. ~5 min
- [ ] Find which update path keeps creating an empty `bin` directory; it was archived 70 times into `trash/` on 2026-11-15. `archive_path` now removes empty directories instead of trashing them, so the churn is invisible, but the source is still unknown. ~20 min

## Needs a model run or device

### Requires user input

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/benchmarks/asr/coverage.py). ~45-60 min

### Unattended

- [ ] Explain why generation stops after a few tokens at a 96K prompt: reasoning on returns only `<think>`,
  reasoning off a 17-token fragment, both far under a 256-token budget, while 32K, 40K and 64K answer fully.
  Probe once with a plain long-generation prompt at 96K: if that also stops early the deep allocation is the
  cause, and if it runs the fault is in the rewrite prompt or the grading path. [Result](../scripts/tests/notes/OUTCOMES.md).
  ~30 min
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The pair now exists on ROCm for `proverb` and `ledger` (27B 23.2 s and 59.3 s against Strata's 74.1 s and 144.0 s, Pi client), but the Vulkan arm still needs the b12422 crash resolved before it can be repeated on the default build. Turn-budget cleanup stays unverified. [Results](../scripts/tests/notes/OUTCOMES.md). ~1 h
