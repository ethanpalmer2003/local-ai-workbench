# llama.cpp tuning

- Owners: [profiles](../../launchers/llamacpp/llamacpp_profiles.py), [native INI](swift-q3.ini), [service/build selection](../../launchers/launcher_config.py).
- Profile values override INI; the launcher supplies the selected model. Request sampling/reasoning may override startup defaults.
- Coding default: `swift15` (96K capacity, Q8 KV, FA on, one slot; benchmark reasoning low, normal launcher medium) on the **Vulkan** build. The allocation decides the build: at 96K Vulkan prefills a 3044-token prompt in 11.5 s against ROCm's 46.7 s (526 against 130 tok/s), while ROCm decodes faster (216 against 199 tok/s on fresh code, 83 against 71 on a rewrite). At 64K the same runner reads 526 against 551 tok/s, so ROCm collapses only between 64K and 96K. It wins at 8K (585 against 528 tok/s prefill, 215 against 192 decode) and needs the iGPU hidden to load at all ([upstream](../../../notes/UPSTREAM-INDEX.md), [note](../../../notes/reviews/ROCM-DRIVER-TIMEOUT-2026-11-13.md)); select it with `--build rocm-lemonade` when the context fits. The Lemonade *server* is a separate language-practice framework; it is not this build.

| Choice | Evidence / limitation |
| --- | --- |
| MTP depth 2 | Rotated 2/3/4 trials averaged 37.16/35.87/35.42 tok/s; depth 2 shortest aggregate request time. Short English/code scope, not a universal optimum |
| Ngram 24/48/64 | Two paired source-copy tasks: decode +18.9%, request time +4.3%; four fresh-generation rounds showed no meaningful penalty, not formal equivalence |
| Q8 K/V | Lower memory than f16; answer-quality loss and Q4 KV not evaluated |
| Prefill measured | The profile runner now sends one cold request per prompt: `prompt_per_second` is reported next to decode, with `cache_n` showing reuse. The 32K filled-context run measured 505 tok/s cold prefill and a 63.3 s TTFT |
| GPU layers 99 | Working full-offload request/cap, not an actual layer count or sweep result |
| Flash Attention | Operational compatibility established; isolated speed/quality effect not measured |
| One slot | Interactive workload/context choice; no universal ngram restriction implied |

- Legacy ngram 32/4/8 remains a named profile. Do not combine unrelated screens into a stronger claim.
- Optional `swift15-8k`: short greedy screen rose from 38.02 to 57.26 tok/s versus 96K capacity, with identical 64-token outputs. Use only when complete prompt/history/output fits; filled-context/everyday-sampling performance remains unverified.
- Screens recorded 2026-10-04: MTP evidence (../../tests/output/llamacpp/benchmark_speedbench/verified/1791093433528713400/artifacts/comparison.md), copy evidence (../../tests/output/llamacpp/benchmark_ngram/no-gain/1791087672992167800/artifacts/comparison.md).
- Profile screen 2026-11-11, b1372, short built-in prompts: cold prefill 43.4 tok/s over a 39-token prompt and decode 63.6 tok/s for `swift15`; 48.8 and 25.5 for `swift15-mtp-notemplate`. One run, code prompt spread is wide. Output: ../../benchmarks/output/llamacpp/benchmark_llamacpp_profiles/unreviewed/1794440590360444400/artifacts/llama-benchmark-summary-20261111-174436.txt
- Long-context screen 2026-11-13, `swift15` against `swift15-nospec` on Vulkan b12363: 39.4 against 28.4 tok/s at 16384 and 44.2 against 26.8 at 32768, warm TTFT 1.3-1.6 s, cold prefill 490 and 431 tok/s. The gain grows with depth while the no-speculation rate stays flat, so the short-prompt ngram result holds at depth. Same day, 32768 against ROCm b1375: prefill 505 against 431 tok/s, decode 51.2 against 43.2 tok/s mean, warm TTFT 1.33 against 1.60 s. The 65536 allocation closes the gap (526 against 551 tok/s), which is where the build switch earns its keep. Output: ../../benchmarks/output/llamacpp/benchmark_context_stream/inconclusive/1794596215793306500 (32k Vulkan spec), 1794596619011805200 (32k Vulkan nospec), 1794596406205251400 (16k Vulkan), 1794596831140867800 (16k Vulkan nospec), 1794601037578896800 (32k both builds), 1794603717416970300 (64k both builds).
- [HRX limits](HRX.md), [model benchmarks](../../benchmarks/MODEL-COMPARISONS.md), [pending grids](../../../notes/TODO.md).
