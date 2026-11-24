# TODO

- Work that will happen: the decision is made and the owner is linked; open choices live in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).
- Entries do not authorize live tests, package changes or long runs. Upstream defects stay in [UPSTREAM](UPSTREAM-INDEX.md), evidence in [STATUS](../scripts/tests/notes/STATUS-INDEX.md).
- Each entry ends with a rough duration.

## Broken now
Work that failed when last tried; the recorded state, not re-tested today. A diagnosis or fix comes before new comparisons.

- [ ] Make the latest HRX stack see the GPU: `llama-server` builds against `hrx-system` `b6ad3f37e` with the registered API-port patch, but the staged `hrx-info` reports `amdgpu: 0 devices` with the new and the installed `hsa-runtime64.dll`, so ROCr/HAL device enumeration is the next fault. Also restore `scripts/benchmarks/llamacpp/hrx/hrx_tensor_probe.cpp`, which is missing from the repository and currently replaced by the installed probe binary. [HRX limits](../scripts/config/llamacpp/HRX.md). ~2 h

- [ ] Take the Loom device failure upstream once it is confirmed, then retry the comparison: it now reproduces on the installed release - `loom-serve --device=amdgpu`, `rdna`, `rdna://1` and `amdgpu://1` all exit 1 with `NOT_FOUND; no AMD endpoint matches the selected family and path` (`runtime/src/iree/hal/driver/amd/driver.c:843`) whatever `HIP_VISIBLE_DEVICES` or `ROCR_VISIBLE_DEVICES` say, while `amdf-info --device=rdna --activate` reports `Activation: OK` on `rdna://0`, the integrated adapter, and `--format=json` lists the RX 7800 XT as `gfx1102`, ordinal 1. `--device=task` starts and registers `Qwen/Qwen2.5-0.5B-Instruct`, but a chat request was still 503 after four minutes. Next: let the CPU path finish to prove the package and the server, then try an explicit device document, and only then write the upstream question; the console scripts need `PYTHONPATH` pointing at `frameworks/loom/sdk`, since their shims load the `loom` package from beside them, and `loom-fetch` writes its hub cache into `data/huggingface/models` unless `--cache` names `data/huggingface/hub`, which the layout check reads as an unregistered model root. The symptom is recorded in [upstream](../notes/UPSTREAM-INDEX.md). Baseline for the same GGUF on llama.cpp Vulkan 1.0.0-dev (12422, a681a53b6): 472 tok/s median over five 128-token runs. ~2 h

- [ ] Validate Handy microphone selection, dictation and paste. `selected_microphone` is null and the last attempt captured 0 samples in 17 ms, so the device is the suspect; model, VAD and hotkey are configured. ~30-45 min

- [ ] Finish live voice-practice checks on both chat consumers: pipelining, capture, playback and echo. Saved-PCM path passes; the browser mic returns audio requests but no transcript. [Scenario matrix](../scripts/launchers/asr/MULTIUSE-SCENARIOS.md). ~45-60 min

- [ ] Measure multilingual/noisy accuracy and microphone latency: capture produced no transcript, and only the English clips have been scored although the pinned corpus carries twenty each of English, Spanish, French and Japanese. [Evaluation](asr/ASR-EVALUATION.md), [coverage inventory](../scripts/benchmarks/asr/coverage.py). ~45-60 min

- [ ] Explain why generation stops after a few tokens at a 96K prompt: reasoning on returns only `<think>`,
  reasoning off a 17-token fragment, both far under a 256-token budget, while 32K, 40K and 64K answer fully.
  Probe once with a plain long-generation prompt at 96K: if that also stops early the deep allocation is the
  cause, and if it runs the fault is in the rewrite prompt or the grading path. [Result](../scripts/tests/notes/OUTCOMES.md).
  ~30 min

- [ ] Find why dead code survived the gate: `cleanup._report` was unused for a while without a finding, and the scoped scan is the suspect, since a definition left in an unchanged file goes unseen when its caller is deleted elsewhere and `verdict_cannot_change` then skips that file. Reproduce with a throwaway module and a caller in a second file, then decide whether the section scans the modules a change references. ~30 min

- [ ] Make a ComfyUI update finish inside the run that started it: when the vendor updater script changed, `comfyui-rocm-updater.bat` starts `_updater_relaunch.bat` in its own console, which inherits the job's output pipe, does the work outside our log and stops at `pause`, so `update_frameworks --yes` printed UPDATED and never returned. Today it did update (`9f041c1`), and the window had to be stopped and the relaunch batch trashed by hand. Decide whether the wrapper follows `.last_update_hash` and stops the window it caused, or skips the app update and documents the manual step. ~45 min

## Needs your input
Decisions only you can make.

- [ ] Decide what to do with the HRX archive. None of the four retained patches applies to the current upstream heads (llama.cpp `76c3785b9`, HRX `b81ff778b`, rocm-systems `0ca1de96e9`), `tests/test-hrx-ops.cpp` no longer exists, and upstream has since landed its own IQ3_XXS decoding (#200, #175). Options: keep the tracked patches, snapshots and checkouts as a dated record, or trash the checkouts and snapshots and keep [the patch directory](../scripts/config/llamacpp/hrx-patches/README.md). ~15 min

- [ ] Judge the Q2_K and Q4_K_M encoder pair on quality: both clips were saved and only timing was written up, so watch the two and record which one keeps. [Screen](reviews/COMFYUI-VIDEO-2026-11-09.md). ~15 min

## Unattended
Code work that runs here without a live model.

- [ ] Finish adopting ruff `B` (bugbear): 33 findings remain, 28 are `B023` closures that capture a loop variable, 3 are `B904` (`raise ... from err`), 1 is an unused loop variable. Bind each captured name in the default (`lambda prompt=prompt: ...`) after confirming the callback is not called with that parameter positionally, then add `B` to `select`. Six other `B` findings (`B905`, `B007`) are already fixed, and `B009` stays reverted because ComfyUI's `INPUT_TYPES` is dynamic. ~1 h

- [ ] Replace the custom line-length check with ruff `E501` and delete the 5.7 s gate section: measure the `E501` hit list first, because the current check exempts template and token lines, then keep the exemption as a handful of per-file ignores. ~30 min

- [ ] Replace the five literal catalog labels in `launcher_speech.py` with `ModelId` names against [models](../scripts/config/models/README.md); the rename tool rewrites the strings today, so they are consistent but untyped. ~15 min

- [ ] Merge the two import rewriters (`rename_path` and `rewrite_imports`): they overlap, and the duplicate baseline records the shared block, so a merge needs a behavior-parity pass first. ~30-45 min

- [ ] Consolidate the llama.cpp profile runner onto `trial.running_server`; the hand-rolled lifecycle is live-only, so the change needs a run that proves identical results. ~1 h

- [ ] Hash-check the installed catalog weights once: the download path now verifies each new transfer's `sha256`, but weights installed before that check have never been compared, and `download_model` still skips an existing file by size alone. Read every `catalog.json` entry with a recorded digest, report mismatches, and decide whether a mismatch is re-downloaded or moved to trash. ~30 min for the small ones, ~1 h if the large multimodal weights are included

## Nice to have, deferred
Quality comparisons and swaps that wait on time, a release or an install. Not failures.

- [ ] Judge Inkling 2 Mini on harder tasks against the 27B. On 2026-11-23 at 32K, Pi, one repeat, all three local coding tasks passed on both builds: mainline `vulkan` b12651 (f5e6915c2) ran the `Mainline_Support` copy at 32.1, 26.5 and 30.3 s (median 30.3) with 43.0 tok/s decode and 607 prefill, while `unsloth` b12649-mix c7059d6 ran the root copy with DSpark at 28.3, 55.7 and 40.8 s (median 40.8) with 54.1 decode at 80% acceptance and 195 prefill; the 27B's two-task median is 35.2. Hard-task quality is still unmeasured, and mainline still rejects the DSpark drafter on a vocab mismatch. [Ranking](../scripts/benchmarks/CODING-ENGINE-RANKING.md). ~1 h

- [ ] Screen Strata against 27B on harder coding/output-format tasks; verify turn-budget cleanup. A paired 64K run on the rolling vulkan build b12602 with Pi, one repeat each, passed both tasks on both arms: Strata median 60.4 s against the 27B's 43.6 s (`whitespace` 58.2 against 19.8, `ledger` 62.6 against 67.5), at 162/30.0 tok/s prefill/decode against 468/55.2, and 33,978 total tokens against 23,782. Strata lost the short task and won the two-file one; harder tasks and turn-budget cleanup stay unmeasured. The app has since moved to 0.2.18 with control and engine 0.1.64, so rerun the pair on that bundle rather than comparing against the 0.1.60 row. [Results](../scripts/tests/notes/OUTCOMES.md). ~1 h

- [ ] Add a comparison row for RustingStrata and LexiEngine. Neither is installed: RustingStrata needs a Vulkan 1.3 driver with subgroup 32 (or fixed 64), device-coherent memory for CPU-resident experts, and tunable `STRATA_VK_*` switches; LexiEngine ships as a USB image or a Linux/WSL install, so Windows means WSL2 with GPU passthrough. Both speak an OpenAI-compatible API, so the `--engine endpoint` arm of `benchmark_coding_engines` is the one to point at them; their caveats are in [the engine notes](../scripts/benchmarks/inference_engines/README.md). ~2 h

- [ ] Swap the two large coding models from static IQ quants to Unsloth dynamic ones once their Qwen4 builds exist: Flash Next behind the Strata profiles ([decode](../scripts/config/strata/decode.json), [prefill](../scripts/config/strata/prefill.json)) is IQ2_XS and the 27B coding model is IQ3_XXS ([catalog](../scripts/config/models/catalog.json)), so the swap is one comparison per model at the same bit budget, quality first and decode second. ~2 h
