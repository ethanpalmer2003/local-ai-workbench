# ComfyUI tuning

Measured settings for this GPU, an RX 7800 XT under ROCm. The runner and its procedures are in the
[video benchmark](../../benchmarks/personal/comfyui/README.md); this page owns the settings that stay.

## Default launch case

`bat/browser/comfyui/launch_comfyui.bat` starts the `smart-memory-off-0111` case: Sage attention,
cache off, flash-attention Triton autotune on, Triton backend off, dynamic VRAM on, smart memory off.

- Change one flag at a time through `--launch-case` (`smart-on`, `autotune-off`, `triton-on`,
  `dynamic-off`) and keep the default until a comparison shows a gain.
- Smart memory stays off; the other three flags have isolated runs only, not a settled default.

## What the screens measured

- Screen at square-equivalent 480, then confirm at 640. Prior scaling found 1024/256 spatial tiling
  raised total time at 640 by 84.6%, so a small-resolution gain did not scale.
- Record decode and total time separately; sampled VRAM is a lower bound, and prompt-cache warmth and
  GPU-monitor overhead are separate factors.

## Not measured yet

Appearance and listening review, autotune and cache effects, monitor overhead, 640 confirmation of the
480 winners, and longer clips. [TODO](../../../notes/TODO.md) owns the pending work.
