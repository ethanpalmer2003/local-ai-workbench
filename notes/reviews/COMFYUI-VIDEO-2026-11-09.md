# ComfyUI video screen at 640: 5 s, 10 s and pinned memory

Screen, not a ranking. Evidence from 2026-11-09 on this machine.

## What ran

`scripts.benchmarks.personal.comfyui.comfyui_video` ran the saved LTX 2.5 i2v workflow at square-equivalent 640, 24 fps, dynamic VRAM on, sage attention on, with the Q2_K and Q4_K_M Gemma 4 12B encoders paired against the same `LTX25-distilled-DiT-Q3_K_M` UNet. Nine attempts were launched; four produced results rows.

| case | encoder | wall | sampler | VAEDecode | process peak | total peak |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 5 s baseline | Q2_K | 118.3 s | 80.7 s | 30.4 s | 12.9 GiB | 14.0 GiB |
| 5 s baseline | Q4_K_M | 119.3 s | 81.1 s | 31.6 s | 12.9 GiB | 14.1 GiB |
| 5 s pinned-on | Q2_K | 124.5 s | 84.6 s | 31.9 s | 12.9 GiB | 14.3 GiB |
| 5 s pinned-on | Q4_K_M | 128.6 s | 87.5 s | 31.6 s | 12.9 GiB | 14.5 GiB |
| 10 s | Q2_K | 243.9 s | 200.9 s | 32.4 s | 13.2 GiB | 15.7 GiB |
| 10 s | Q4_K_M | 231.3 s | 189.3 s | 32.3 s | 13.3 GiB | 15.7 GiB |

Peaks are sampled lower bounds, not exact maxima. The first 5 s pair (155.9 and 158.9 s, 15.4 GiB total peak) is the cold launch: its totals include model loading, so it is excluded from the comparison above.

## Reading

- VAEDecode stays near 30 to 32 s in every case, so the extra time of a longer clip lands in sampling.
- Ten seconds is roughly twice the wall time of five and saturates the card within about 300 MiB of 16 GiB: viable, but with no headroom for a larger resolution.
- Pinned memory is 5 to 8 percent slower and adds 300 to 400 MiB of sampled total peak. It stays off.

## If this holds

640 at 5 s would be the default this machine runs with headroom; 10 s would stay an opt-in for longer clips, and pinned memory would stay off. No default changed.

Evidence: `scripts/benchmarks/output/personal/comfyui/comfyui_video/unreviewed/1794268833104865200` (baseline), `1794269103117986800` (pinned-on), `1794269678150814900` (10 s).
