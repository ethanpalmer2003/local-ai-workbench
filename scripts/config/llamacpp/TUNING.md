# llama.cpp tuning

- Owners: [profiles](../../launchers/llamacpp/llamacpp_profiles.py), [native INI](swift-q3.ini), [service/build selection](../../launchers/launcher_config.py).
- Profile values override INI; the launcher supplies the selected model. Request sampling/reasoning may override startup defaults.
- Coding default: `swift15`, Lemonade ROCm, 96K capacity, Q8 KV, FA on, one slot; benchmark reasoning low, normal launcher medium.

| Choice | Evidence / limitation |
| --- | --- |
| MTP depth 2 | Rotated 2/3/4 trials averaged 37.16/35.87/35.42 tok/s; depth 2 shortest aggregate request time. Short English/code scope, not a universal optimum |
| Ngram 24/48/64 | Two paired source-copy tasks: decode +18.9%, request time +4.3%; four fresh-generation rounds showed no meaningful penalty, not formal equivalence |
| Q8 K/V | Lower memory than f16; answer-quality loss and Q4 KV not evaluated |
| GPU layers 99 | Working full-offload request/cap, not an actual layer count or sweep result |
| Flash Attention | Operational compatibility established; isolated speed/quality effect not measured |
| One slot | Interactive workload/context choice; no universal ngram restriction implied |

- Legacy ngram 32/4/8 remains a named profile. Do not combine unrelated screens into a stronger claim.
- Optional `swift15-8k`: short greedy screen rose from 38.02 to 57.26 tok/s versus 96K capacity, with identical 64-token outputs. Use only when complete prompt/history/output fits; filled-context/everyday-sampling performance remains unverified.
- Screens recorded 2026-10-04: [MTP evidence](../../tests/output/llamacpp/benchmark_speedbench/verified/1791093433528713400/artifacts/comparison.md), [copy evidence](../../tests/output/llamacpp/benchmark_ngram/no-gain/1791087672992167800/artifacts/comparison.md).
- [HRX limits](HRX.md), [model benchmarks](../../benchmarks/MODEL-COMPARISONS.md), [pending grids](../../../notes/TODO.md).
