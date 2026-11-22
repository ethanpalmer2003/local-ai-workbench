# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration, shortest first.

## Needs a model run or device
Work that cannot be settled without a live run: weights, a device, a server or a human at the machine.

- [ ] Judge Inkling 2 Mini against the 27B on harder tasks. The vendor build is installed as `llamacpp/unsloth` (b12588-mix-c0c3de8, Vulkan); with the repository-root GGUF and the DSpark drafter it passed both local tasks 2/2 at a 67.6 s median against the 27B's 35.2 s, at 32K, Pi, one repeat each. Mainline 12602 loads the Mainline_Support copy but never produces usable content or a tool call, and its drafter pairing is rejected by a vocab mismatch. Quality is unmeasured. ~1 h

- [ ] Pin every inference engine to the tracked discrete adapter. llama.cpp's Vulkan builds now resolve it by name ([hardware.json](../scripts/config/shared/hardware.json), [gpu_selection.py](../scripts/launchers/runtime/gpu_selection.py)) and refuse when it is missing, but AudioCpp (`--device 0`), sd.cpp (`Vulkan0`), Strata (`gpu: 0`) and the ROCm builds (`HIP_VISIBLE_DEVICES=0`) still assume device order, so an adapter-order change could benchmark the integrated GPU and pass. ~45 min

### Requires user input

- [ ] Decide whether to keep the rejected patch export of local HRX work. `scripts/state/llamacpp/hrx/local-work` holds two llama.cpp patches (133,873,695 and 134,054,355 bytes) carrying the squashed history that cannot be committed, beside a manifest and README; the same commits are 180 KB of git bundles in [the tracked local-work folder](../scripts/download/frameworks/llamacpp/hrx/local-work/README.md), which also keeps hrx-system and rocm-systems patch copies next to their 10 KB and 5 KB bundles. Options: delete the state copy (about 268 MB) and the two redundant tracked patches, or keep the patches as readable text. Deletion needs approval. ~5 min

- [ ] Decide what to do with the HRX archive. None of the four retained patches applies to the current upstream heads (llama.cpp `76c3785b9`, HRX `b81ff778b`, rocm-systems `0ca1de96e9`), `tests/test-hrx-ops.cpp` no longer exists, and upstream has since landed its own IQ3_XXS decoding (#200, #175). Options: keep the tracked patches, snapshots and checkouts as a dated record, or trash the checkouts and snapshots and keep [the patch directory](../scripts/config/llamacpp/hrx-patches/README.md). ~15 min

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min
- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min
- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min
- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript and no multilingual corpus is configured. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/benchmarks/asr/coverage.py). ~45-60 min

### Unattended

- [ ] Add a comparison row for RustingStrata and LexiEngine. Neither is installed: RustingStrata needs a Vulkan 1.3 driver with subgroup 32 (or fixed 64), device-coherent memory for CPU-resident experts, and tunable `STRATA_VK_*` switches; LexiEngine ships as a USB image or a Linux/WSL install, so Windows means WSL2 with GPU passthrough. Both speak an OpenAI-compatible API, so the `--engine endpoint` arm of `benchmark_coding_engines` is the one to point at them; their caveats are in [the engine notes](../scripts/benchmarks/inference_engines/README.md). ~2 h
- [ ] Make the latest HRX stack see the GPU: `llama-server` builds against `hrx-system` `b6ad3f37e` with the registered API-port patch, but the staged `hrx-info` reports `amdgpu: 0 devices` with the new and the installed `hsa-runtime64.dll`, so ROCr/HAL device enumeration is the next fault. Also restore `scripts/benchmarks/llamacpp/hrx/hrx_tensor_probe.cpp`, which is missing from the repository and currently replaced by the installed probe binary. [HRX limits](../scripts/config/llamacpp/HRX.md). ~2 h

- [ ] Explain why generation stops after a few tokens at a 96K prompt: reasoning on returns only `<think>`,
  reasoning off a 17-token fragment, both far under a 256-token budget, while 32K, 40K and 64K answer fully.
  Probe once with a plain long-generation prompt at 96K: if that also stops early the deep allocation is the
  cause, and if it runs the fault is in the rewrite prompt or the grading path. [Result](../scripts/tests/notes/OUTCOMES.md).
  ~30 min
- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. A paired 64K run on the rolling vulkan build b12602 with Pi, one repeat each, passed both tasks on both arms: Strata median 60.4 s against the 27B's 43.6 s (`whitespace` 58.2 against 19.8, `ledger` 62.6 against 67.5), at 162/30.0 tok/s prefill/decode against 468/55.2, and 33,978 total tokens against 23,782. Strata lost the short task and won the two-file one; harder tasks and turn-budget cleanup stay unmeasured. The app has since moved to 0.2.18 with control and engine 0.1.64, so rerun the pair on that bundle rather than comparing against the 0.1.60 row. [Results](../scripts/tests/notes/OUTCOMES.md). ~1 h
- [ ] Take the Loom device failure upstream once it is confirmed, then retry the comparison: it now reproduces on the installed release - `loom-serve --device=amdgpu`, `rdna`, `rdna://1` and `amdgpu://1` all exit 1 with `NOT_FOUND; no AMD endpoint matches the selected family and path` (`runtime/src/iree/hal/driver/amd/driver.c:843`) whatever `HIP_VISIBLE_DEVICES` or `ROCR_VISIBLE_DEVICES` say, while `amdf-info --device=rdna --activate` reports `Activation: OK` on `rdna://0`, the integrated adapter, and `--format=json` lists the RX 7800 XT as `gfx1102`, ordinal 1. `--device=task` starts and registers `Qwen/Qwen2.5-0.5B-Instruct`, but a chat request was still 503 after four minutes. Next: let the CPU path finish to prove the package and the server, then try an explicit device document, and only then write the upstream question; the console scripts need `PYTHONPATH` pointing at `frameworks/loom/sdk`, since their shims load the `loom` package from beside them, and `loom-fetch` writes its hub cache into `data/huggingface/models` unless `--cache` names `data/huggingface/hub`, which the layout check reads as an unregistered model root. The symptom is recorded in [upstream](../notes/UPSTREAM-INDEX.md). Baseline for the same GGUF on llama.cpp Vulkan 1.0.0-dev (12422, a681a53b6): 472 tok/s median over five 128-token runs. ~2 h

### Waiting on a release

- [ ] Swap the two large coding models from static IQ quants to Unsloth dynamic ones once their Qwen4 builds exist: Flash Next behind the Strata profiles ([decode](../scripts/config/strata/decode.json), [prefill](../scripts/config/strata/prefill.json)) is IQ2_XS and the 27B coding model is IQ3_XXS ([catalog](../scripts/config/models/catalog.json)), so the swap is one comparison per model at the same bit budget, quality first and decode second. ~2 h
