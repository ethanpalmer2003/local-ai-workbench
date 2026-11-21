# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Needs a model run or device
Work that cannot be settled without a live run: weights, a device, a server or a human at the machine.

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
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. The pair now exists on ROCm for `proverb` and `ledger` (27B 23.2 s and 59.3 s against Strata's 74.1 s and 144.0 s, Pi client). The Vulkan arm now runs on the rolling b12590 default: `whitespace` 23.2 s and `ledger` 65.9 s, both passed, about 10% slower than ROCm. The Strata arm still cannot start (its control python fails with `[WinError 5]`, the 0.1.60 image-encoder fault), so the pair is half measured. Turn-budget cleanup stays unverified. [Results](../scripts/tests/notes/OUTCOMES.md). ~1 h
- [ ] Take the Loom device failure upstream once it is confirmed, then retry the comparison: it now reproduces on the installed release - `loom-serve --device=amdgpu`, `rdna`, `rdna://1` and `amdgpu://1` all exit 1 with `NOT_FOUND; no AMD endpoint matches the selected family and path` (`runtime/src/iree/hal/driver/amd/driver.c:843`) whatever `HIP_VISIBLE_DEVICES` or `ROCR_VISIBLE_DEVICES` say, while `amdf-info --device=rdna --activate` reports `Activation: OK` on `rdna://0`, the integrated adapter, and `--format=json` lists the RX 7800 XT as `gfx1102`, ordinal 1. `--device=task` starts and registers `Qwen/Qwen2.5-0.5B-Instruct`, but a chat request was still 503 after four minutes. Next: let the CPU path finish to prove the package and the server, then try an explicit device document, and only then write the upstream question; the console scripts need `PYTHONPATH` pointing at `frameworks/loom/sdk`, since their shims load the `loom` package from beside them, and `loom-fetch` writes its hub cache into `data/huggingface/models` unless `--cache` names `data/huggingface/hub`, which the layout check reads as an unregistered model root. The symptom is recorded in [upstream](../notes/UPSTREAM-INDEX.md). Baseline for the same GGUF on llama.cpp Vulkan 1.0.0-dev (12422, a681a53b6): 472 tok/s median over five 128-token runs. ~2 h

### Waiting on a release

- [ ] Swap the two large coding models from static IQ quants to Unsloth dynamic ones once their Qwen4 builds exist: Flash Next behind the Strata profiles ([decode](../scripts/config/strata/decode.json), [prefill](../scripts/config/strata/prefill.json)) is IQ2_XS and the 27B coding model is IQ3_XXS ([catalog](../scripts/config/models/catalog.json)), so the swap is one comparison per model at the same bit budget, quality first and decode second. ~2 h
