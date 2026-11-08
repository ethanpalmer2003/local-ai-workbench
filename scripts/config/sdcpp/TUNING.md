# SD.cpp tuning

How the image stack is configured on this machine, an RX 7800 XT. Build/model selection and launch live
in the [backend configuration](README.md); the measured screens are [quantized memory](Q4-MEMORY.md),
[full-precision memory](MEMORY.md) and [quantized checkpoint](QUANTIZED.md).

Screens recorded 2026-10-26 for the quantized checkpoint; the full-precision screen predates them and carries a commit, not a date.

## What is in use

- Default build Vulkan, checkpoint `nova3d-q4`, no CPU offload and no VAE tiling; ROCm is a retained
  alternative and is not the current default.
- Settings are screened one at a time. Do not add two savings together, and assume no combination was
  measured unless a comparison says so.

## Why these settings

- CPU text encoding and smaller VAE tiles buy VRAM with host RAM and decoding time, so neither is the
  default; the trade-off tables are in the memory screens above.
- The quantized checkpoint is the default; the full-precision numbers are historical and do not
  describe it.

## Not measured yet

The current release under ROCm, combinations of the individual settings, and visual quality. A screen is
opt-in and reruns only when requested; `notes/TODO.md` owns the remaining work.
