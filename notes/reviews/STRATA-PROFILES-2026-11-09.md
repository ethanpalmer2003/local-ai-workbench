# Strata profile pair: prefill ahead on a fresh prompt

Screen, not a ranking. Evidence from 2026-11-09 on this machine.

## What ran

`scripts.benchmarks.coding_agents.strata_profiles` ran both configured profiles against the same IQ2_XS weights: one warmup, then three resident requests of a 3025-token fresh prompt with 128 output tokens, reasoning off. The decode profile carries `--resident-budget-gib 8`; without a budget its auto expert cache committed the pack and the 1 GiB RAM floor ended the arm before sampling.

| profile | startup | TTFT | prompt read | decode | sampled min RAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| `prefill.json` | 40.6 s | 10.4-10.7 s | 284-292 tok/s | 29.3-30.4 tok/s | 2.65 GiB |
| `decode.json` | 19.3 s | 21.6-23.2 s | 130-141 tok/s | 18.9-25.9 tok/s | 2.94 GiB |

- Draft acceptance is higher on the prefill arm (0.71-0.74 against 0.52-0.55), which explains part of its decode lead.
- Total wall time was 96.5 s for prefill and 124.8 s for decode, including startup.

## Older numbers disagree

The 2026-10-26 reference harness measured decode at 36.9 and prefill at 24.6 tok/s, the opposite order. That harness no longer describes a runnable configuration here: today's decode profile only completes with the resident budget. Earlier pairs from the same current runner are `1794267679921389200` and `1794267836498567100`. Treat the date and harness of a Strata number as part of the number.

## If this holds

Long fresh prompts would want `prefill.json`; many warm short turns would want `decode.json`, which starts 21 s sooner and reads cached prompt tokens at no cost either way. A second pair agreeing would make prefill the default for read-heavy use. One pair is not enough.

No default changed.

Evidence: `scripts/benchmarks/output/coding_agents/strata_profiles/unreviewed/1794271262458607300`.
