# sd.cpp

- `SDCPP_SERVICE` selects build and model; the current pairing and its evidence are in `TUNING.md`. One-launch overrides: `--build rocm|vulkan`, `--model-profile nova3d|nova3d-q4`.
- Canonical installs: `frameworks/sdcpp/{rocm,vulkan}`. DLLs stay with the selected build; do not inject the unrelated SDK directory.
- Both variants remain updated: `bat/update_frameworks.bat --only sdcpp`. ROCm runtime use is deferred, not removed.
- Launch: `bat/browser/launch_sdcpp.bat`; it opens sd.cpp's built-in web UI at `/`. Server/proxy code lives in `launchers/sdcpp/`.
- Readiness owner: [backend_readiness.py](../../launchers/runtime/backend_readiness.py); current native route `/v1/models` rather than `/health`.
- Native models, LoRAs, generation defaults and proxy behavior remain in `launcher_config.py`. Paths are `Path` internally and serialized at native boundaries.
- Saving -> `SDCPP_SAVE_OUTPUTS`; `SDCPP_OUTPUT_DIR` remains a Path.
- [Tuning](TUNING.md) owns what is in use and what stays unmeasured; measured screens: [quantized checkpoint](QUANTIZED.md), [quantized memory](Q4-MEMORY.md), [full-precision memory](MEMORY.md).
- Shared residency: CPU text encoder/512 VAE tiles through [shared GPU policy](../notes/SHARED-GPU.md). [Image swapping](../notes/IMAGE-ON-DEMAND.md) uses native management without normal server replacement.
- Comparison modules: `scripts.benchmarks.personal.sdcpp.sdcpp_backend_compare`, `sdcpp_memory_compare`; opt-in, fresh/warmup/measured phases, identical seeds/prompts, sampled resources.
- Prior single-order/backend screens do not rank visual quality or predict current releases. Preserve failures, RAM guard and owned-session cleanup.
