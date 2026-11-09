# Quantized memory tests

- Vulkan / RX 7800 XT; 1024x1024, 25 Euler A steps, CFG 4, CLIP skip 2, seed 42, CPU RNG, 8 threads.
- One fresh server, full warmup and two measured images per case; matched prompts, direct convolution fixed on.
- Outside AppContainer, nonadministrator; 100 ms whole-adapter VRAM sampling, 0.5 s CPU/RAM/I/O sampling.
- Times exclude startup/warmup; both retained in raw results. Single ordered screen; background GPU/disk/CPU activity not isolated.

| Setting | s/image | Time change | Median / peak VRAM GiB | Peak server RAM GiB |
| --- | ---: | ---: | ---: | ---: |
| baseline | 27.65 | +0.0% | 5.38 / 8.61 | 0.23 |
| text-encoder-cpu | 27.75 | +0.4% | 4.77 / 8.01 | 0.82 |
| vae-tile-512 | 29.19 | +5.6% | 5.50 / 6.17 | 0.31 |
| vae-tile-256 | 30.43 | +10.1% | 5.39 / 5.45 | 0.27 |
| cpu-weights-budget-8 | 28.50 | +3.1% | 4.76 / 6.25 | 2.71 |
| text-cpu-and-vae-512 | 29.64 | +7.2% | 4.92 / 5.60 | 0.77 |

- 512 tiles: balanced low-RAM choice; about 2.44 GiB lower peak for 1.55 s more per image.
- CPU-held weights: about 2.37 GiB lower peak for 0.86 s more; both measured images pixel-identical to baseline.
- 256 tiles: lowest measured peak (5.45 GiB), about 10.1% slower.
- Combined text CPU/512 tiles: 5.60 GiB peak; lower median (4.92 GiB) than 256 tiles.
- CPU text encoder bursts: 51-53% whole-machine CPU; medians about 2.8-3.0% across cases.
- CPU/tiling outputs differ from baseline; combined image visually checked, no obvious seams. No formal quality score.
- CPU-held weights use a managed 8 GiB budget, not a hard whole-adapter cap.
- Disk I/O traces retained; aggregate system activity includes other applications and is not an SSD benchmark.
- Which of these cases runs is owned by [TUNING](TUNING.md); original full-precision results remain in MEMORY.md.

- Raw run (../../tests/output/probes/sdcpp_memory_compare/unreviewed/1792993847694866300/artifacts/results.json).
- Detailed summaries (../../tests/output/probes/sdcpp_memory_compare/unreviewed/1792993847694866300/artifacts/summary.json).
