# Vulkan memory trade-offs

- Historical full-precision Nova3D SDXL screen, commit `e41fbcf`, RX 7800 XT, 1024x1024, 25 Euler A steps, CFG 4, seed 42; not the current Q4 model.
- Fresh server/full warmup/two measured prompts per case; direct convolution fixed on, no LoRAs. Times exclude startup/warmup; memory peaks are sampled.

| Setting | Seconds/image | Median / peak VRAM GiB |
| --- | ---: | ---: |
| Baseline | 26.98 | 8.79 / 12.05 |
| CPU text encoder | 26.79 | 7.47 / 10.72 |
| VAE tiles 512 | 28.20 | 8.62 / 9.28 |
| VAE tiles 256 | 29.50 | 8.79 / 8.85 |
| CPU weights / 8 GiB managed budget | 27.71 | 7.01 / 7.01 |

- CPU text encoding exchanges VRAM for host RAM; smaller tiles add decoding time. Managed budgets can substantially increase host RAM.
- Settings were screened independently; do not add savings or assume combinations were measured.
- Default backend remains Vulkan; ROCm is a retained alternative. Current quantized model findings: [Q4 memory](Q4-MEMORY.md).
- Rerun through `scripts.benchmarks.personal.sdcpp.sdcpp_memory_compare` only when requested, matching model/hashes/context and recording execution token.
- Historical complete outputs remain under `tests/output/probes/sdcpp_memory_compare/`; source reorganization does not rewrite them.
