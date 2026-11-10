# Saved LTX 2.5 I2V benchmark

- Runner: `scripts.benchmarks.personal.comfyui.comfyui_video`; settings screen: `comfyui_settings`. Saved workflows/assets stay beside this component.
- Current/native workflow ownership: [ComfyUI configuration](../../../config/comfyui/README.md). Native server work is opt-in; reuse/refuse sessions according to the [test rules](../../../tests/README.md).
- Inputs, seeds, frame counts, typed model paths and prompt-cache behavior must match. Record loading/startup separately from generation/decoding.
- Shared timing records startup and workflow totals. Model loading may occur inside nodes/offloading; its separate duration stays unknown. First workflow is marked loading-plus-workflow; these totals never qualify as resident inference rankings.

## Workflow comparison and simplification

- `--compare-workflows` compares fixed saved alternatives; original `fast480` is 97 frames/24 fps, while `fast480_v3` uses 241 video / 240 audio frames and a larger pixel area.
- These workloads differ; do not report their total-time difference as an isolated workflow optimization.
- Historical completed smoke corrected FPS output to FLOAT. Partial/interrupted comparisons remain incomplete.

## Original-VAE tile sweep

- `--tile-sweep`: multiple spatial/temporal configurations; each case needs matched clips and decode plus total-time reporting.
- Smaller tiles may reduce memory while increasing time. Keep original/reference VAE distinct from changed model/workflow conditions.

## Focused settings screens

- Screen at square-equivalent 480; validate promising candidates at 640 before changing general defaults. Ten-second 480 is optional/lower priority.
- The 640 screen (5 s, 10 s, pinned memory) is written up in the dated record, [COMFYUI-VIDEO-2026-11-09](../../../../notes/reviews/COMFYUI-VIDEO-2026-11-09.md). No default changed from it.
- Prior scaling found 1024/256 tiling increased total time at 640 by 84.6%; a small-resolution gain did not scale.
- Prompt-cache warmness and GPU-monitor overhead are separate factors. Benchmark one change at a time; listening/appearance review is additional work.

## Sampled VRAM

- Sampled peaks are lower bounds with missing counters left null; the shared monitor and its limits are owned by [execution and reporting](../../../tests/EXECUTION-AND-REPORTING.md).
- Preserve execution token, counters unavailable/null values, CPU/RAM and stage labels.
- Historical `tests/output/probes/comfyui_video/` was retired to trash; new results follow `benchmarks/output/comfyui/`.
- [Estimates](../../../tests/notes/ESTIMATES.md), [TODO](../../../../notes/TODO.md). Additional quality/autotune/scaling checks remain deferred.
