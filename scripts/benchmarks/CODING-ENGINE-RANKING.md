# Coding engine ranking

Method: the coding-agent benchmark with Pi, the local `whitespace` and `ledger` tasks, one repeat, 32K context
unless a row says otherwise. 27B arms sample at temperature 0; Inkling uses its own declared sampling. Times
include harness startup and tools. Each row is one engine and model pair, ranked by the median of the two tasks.

## Swift-1.5 27B (IQ3_XXS, ISTA GSQ-RCO)

| Rank | Engine | Build | whitespace | ledger | Median |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | llama.cpp `vulkan` | b12602 418fe97b5 | 22.9 | 47.6 | **35.2** |
| 2 | llama.cpp `vulkan-1.0.0` | b12359 b1b770d90 | 22.3 | 51.4 | 36.9 |
| 3 | llama.cpp `rocm-lemonade` | b1383, llama.cpp 12600 29b52d398 | 21.0 | 76.1 | 48.6 |
| 4 | llama.cpp `unsloth` | b12588-mix c0c3de8 | 32.4 | 71.1 | 51.7 |
| 5 | Strata | control 0.1.60, engine 0.1.59 (64K) | 58.2 | 62.6 | 60.4 |

ROCm led prefill (501 and 502 tok/s) and decode (62.5 and 56.8), but its `ledger` run generated 37,435 tokens
against 24,459 for the rolling build, so its wall time is not a like-for-like rate comparison. The Strata row is
64K because its profile runs there; its older 32K pair read 74.1 and 144.0. Strata was then updated in its own app
to 0.2.18 with control and engine 0.1.64 on 2026-11-21 at 15:34, so the row above measures the 0.1.60 bundle until
the pair runs again.

## Flash Next (IQ2_XS, Strata weights)

1. Strata 0.1.60: 58.2 and 62.6, median 60.4 at 64K.
2. Avalon loads the same weights but only the micro pair exists: decode 27.6-34.1 against Strata's 22.9, prefill
   61-65 against 110.5, and TTFT 46-49 s against 27.4. No task-level row, ranked below Strata.

## Inkling-2-Mini (IQ3_XXS, Unsloth)

1. llama.cpp `unsloth` b12588: 55.0 and 80.2, median 67.6 at 32K. Mainline b12602 loads the
   `Mainline_Support` copy but produced no usable answer or tool call, so it has no row.

## What to run

1. Default coding engine: llama.cpp `vulkan`, the rolling build. It wins the 27B median and supports the widest set
   of models.
2. Long context at 64K and beyond: the same build, since ROCm collapses above 64K.
3. Inkling 2 Mini: `unsloth`; nothing else runs it usefully.
4. Flash Next: Strata; Avalon is the fallback if Strata fails.
5. The pinned `vulkan-1.0.0` and `rocm-lemonade` builds stay installed as fallbacks; both are within a few seconds
   of the rolling build at 32K.

## How to read "latest"

"Latest" means the build installed and measured at the stated date and time, not an open claim about upstream.
The builds above were read on 2026-11-21 at 15:26 (America/Regina): mainline b12602 (418fe97b5), with b12613
offered but not installed; Unsloth b12588-mix-c0c3de8 (883286076); ROCm Lemonade b1383 (29b52d398);
`vulkan-1.0.0` b12359 (b1b770d90); Strata control 0.1.60. Treat a number as reliable for that build and test the
next one rather than assuming it carries over. One repeat per task means a few seconds of noise, not a ranking gap.
