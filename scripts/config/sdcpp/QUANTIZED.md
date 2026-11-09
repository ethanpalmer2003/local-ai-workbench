# Quantized checkpoint

- Working on current Vulkan sd.cpp `e41fbcf`; no conversion or new download required.
- Default profile: `nova3d-q4`. Original full-precision checkpoint remains selectable with `--model-profile nova3d`.
- Launch: `C:/AI/bat/browser/launch_sdcpp.bat --build vulkan --model-profile nova3d-q4`.
- Persistent selection: `SDCPP_SERVICE.model = "nova3d-q4"` in [launcher_config.py](../../launchers/launcher_config.py); restart.
- Model-profile selection applies at startup; request-body model labels do not hot-swap the loaded checkpoint.

## Files / fix

- Quantized GGUF under the sd.cpp model root, 2.6 GiB; the catalog owns its identity.
- Bundled SDXL checkpoint: CLIP-L, CLIP-G, diffusion model and VAE present. GGUF v3, 2514 tensors; 1222 quantized and 1292 F16 tensors, no scalar metadata.
- Use normal `-m` checkpoint loading; the prior commented diffusion-only example was misleading for this file.
- Companion `clip_l.safetensors`, `clip_g.safetensors`, `xlVAEC_c91.safetensors`: not required for the tested bundled path; retained as optional overrides.
- Q4 catalog destination follows the file moved into `sdcpp/`; separate components are optional restore entries. Original Q4 download provenance remains unrecorded; no guessed URL added.
- Earlier failure cause cannot be established from available logs. Current bundled loading/generation is verified; no claim that one particular old runtime bug was fixed.

## Verification

- 512x512 / one-step smoke: passed, using embedded components.
- 1024x1024 / 25 Euler A steps: full warmup plus two distinct measured prompts passed; first output visually checked.
- Full-screen controls: seed 42, CPU RNG, 8 configured threads, CFG 4, CLIP skip 2, direct convolution on, no LoRAs or CPU offload.
- Median image API time: 27.34 s. Sampled measured VRAM: median 5.36 GiB / peak 8.59 GiB. Peak server RAM: 0.23 GiB.
- Native weights: 2678.64 MB on GPU (encoders 585.42, diffusion 1933.54, VAE 159.68).
- Not a fresh paired FP16 quality/speed comparison; quantization changes generated details. LoRA, img2img and other resolutions remain untested.
- GPU capture: 100 ms; CPU/RAM/process-I/O/system-disk traces retained. Whole-adapter VRAM includes other allocations.
- Execution: outside AppContainer, nonadministrator token; RAM/deadline guards and owned-server cleanup used.
- Evidence: full-size run (../../tests/output/probes/sdcpp_backend_compare/unreviewed/1792992877252850000), smoke run (../../tests/output/probes/sdcpp_backend_compare/unreviewed/1792992784486540700).

## Offload / tiling

- All six Q4 cases tested: [results and trade-offs](Q4-MEMORY.md).
- Default remains without offload/tiling.
